import json

import frappe
from frappe import _

from qcmc_logic.qcmc_logics.doctype.production_floor_layout.production_floor_layout import validate_layout


EMPTY_LAYOUT = {"width": 1200, "height": 800, "buildings": []}
SITE_NAMES = ("Guyong", "Sta Clara", "MC 1", "MC 2")


def _site_for_floor(floor):
	"""Map existing floor labels using the site rules supplied by production."""
	company = (floor.company or "").upper().replace(" ", "")
	label = (floor.floor_name or floor.name or "").upper().replace(" ", "")
	if "QCSTYRO" in company:
		return "Sta Clara" if "33" in label else "Guyong"
	if "MULTIPLAST" in company:
		return "MC 2" if ("FORMING-MC2" in label or "INJECTION" in label or "SHRINKWRAP" in label) else "MC 1"
	return None


def _suggested_sites(companies):
	if not companies:
		return {}
	floors = frappe.get_all(
		"Plant Floor", filters={"company": ["in", sorted(companies)]},
		fields=["name", "floor_name", "company"],
	)
	result = {}
	for floor in floors:
		name = _site_for_floor(floor)
		if not name:
			continue
		entry = result.setdefault(name, {"company": floor.company, "plant_floors": []})
		if entry["company"] != floor.company:
			frappe.throw(_("Production Site {0} spans multiple Companies; configure it manually.").format(name))
		entry["plant_floors"].append(floor.name)
	return result


def _company_names():
	if not (set(frappe.get_roles()) & {"Manufacturing User", "Manufacturing Manager", "System Manager"}):
		frappe.throw(_("Manufacturing access required."), frappe.PermissionError)
	return set(frappe.get_list("Company", pluck="name", limit_page_length=0))


def _site(production_site, companies):
	site = frappe.db.get_value("Production Site", production_site, ["name", "site_name", "company"], as_dict=True)
	if site and site.company not in companies:
		frappe.throw(_("Production Site access denied."), frappe.PermissionError)
	if site:
		site.plant_floors = frappe.get_all(
			"Production Site Plant Floor", filters={"parent": site.name}, pluck="plant_floor"
		)
		return site
	if production_site in SITE_NAMES:
		suggested = _suggested_sites(companies).get(production_site)
		if suggested:
			return frappe._dict(name=production_site, **suggested)
	frappe.throw(_("Production Site access denied."), frappe.PermissionError)
	return site


def _can_edit():
	return bool(set(frappe.get_roles()) & {"Manufacturing Manager", "System Manager"})


@frappe.whitelist(methods=["GET"])
def list_sites():
	companies = _company_names()
	suggested = _suggested_sites(companies)
	configured = {
		row.name: row for row in frappe.get_list(
			"Production Site", filters={"company": ["in", sorted(companies)], "name": ["in", SITE_NAMES]},
			fields=["name", "company", "site_name"], limit_page_length=0,
		)
	} if companies else {}
	return [{"name": name, "configured": name in configured or (name in suggested and not frappe.db.exists("Production Site", name))} for name in SITE_NAMES]


@frappe.whitelist(methods=["GET"])
def get_layout(production_site):
	site = _site(production_site, _company_names())
	row = frappe.db.get_value("Production Floor Layout", {"production_site": site.name}, ["layout_json", "layout_version"], as_dict=True)
	return {
		"production_site": site.name, "company": site.company,
		"plant_floors": site.plant_floors,
		"layout": json.loads(row.layout_json) if row else EMPTY_LAYOUT,
		"version": row.layout_version if row else 0,
		"can_edit": _can_edit(),
	}


@frappe.whitelist(methods=["GET"])
def get_floor_context(production_site, shift_date=None, shift_type=None):
	site = _site(production_site, _company_names())
	workstations = frappe.get_list(
		"Workstation", filters={"plant_floor": ["in", site.plant_floors], "disabled": 0},
		fields=["name", "workstation_name", "workstation_type", "plant_floor", "status", "description"], limit_page_length=0,
	) if site.plant_floors else []
	return {"workstations": workstations}


@frappe.whitelist(methods=["GET"])
def get_machine_context(production_site, workstation, shift_date, shift_type=None):
	"""Return permission-filtered details and Process Cards for one placed Workstation."""
	site = _site(production_site, _company_names())
	if not workstation:
		return {"workstation": None, "process_cards": [], "can_create": False, "unavailable": True}
	workstations = frappe.get_list(
		"Workstation",
		filters={"name": workstation, "plant_floor": ["in", site.plant_floors], "disabled": 0},
		fields=["name", "workstation_name", "workstation_type", "plant_floor", "status", "description"],
		limit_page_length=1,
	) if site.plant_floors else []
	if not workstations:
		return {"workstation": None, "process_cards": [], "can_create": False, "unavailable": True}
	filters = {"company": site.company, "workstation": workstation, "shift_date": shift_date}
	if shift_type:
		filters["shift_type"] = shift_type
	cards = frappe.get_list(
		"Process Card", filters=filters,
		fields=["name", "workstation", "shift_date", "shift_type", "status", "docstatus"],
		limit_page_length=100, order_by="shift_date desc, modified desc",
	)
	return {
		"workstation": workstations[0], "process_cards": cards,
		"can_create": bool(frappe.has_permission("Process Card", "create")), "unavailable": False,
	}


@frappe.whitelist(methods=["POST"])
def save_layout(production_site, layout, expected_version):
	site = _site(production_site, _company_names())
	if not _can_edit():
		frappe.throw(_("Layout editing requires a manufacturing manager."), frappe.PermissionError)
	try:
		version = int(expected_version)
		data = json.loads(layout) if isinstance(layout, str) else layout
	except (TypeError, ValueError):
		frappe.throw(_("Invalid layout or version."))
	if type(version) is not int or version < 0:
		frappe.throw(_("Invalid layout version."))
	validate_layout(data, site.plant_floors)
	# Lock Company for first-save creation, then the stable Production Site row.
	frappe.db.sql("select name from `tabCompany` where name=%s for update", site.company)
	if not frappe.db.exists("Production Site", site.name):
		new_site = frappe.get_doc({
			"doctype": "Production Site", "site_name": site.name, "company": site.company,
			"plant_floors": [{"plant_floor": name} for name in site.plant_floors],
		})
		new_site.insert()
	frappe.db.sql("select name from `tabProduction Site` where name=%s for update", site.name)
	current = frappe.db.get_value("Production Floor Layout", {"production_site": site.name}, ["name", "layout_version"], as_dict=True)
	if (current.layout_version if current else 0) != version:
		frappe.throw(_("Layout changed since it was opened. Reload before saving."), frappe.TimestampMismatchError)
	if current:
		doc = frappe.get_doc("Production Floor Layout", current.name)
		doc.check_permission("write")
	else:
		doc = frappe.new_doc("Production Floor Layout")
		doc.production_site = site.name
		doc.company = site.company
	doc.layout_json = json.dumps(data, separators=(",", ":"), allow_nan=False)
	doc.layout_version = version + 1
	if current:
		doc.save()
	else:
		doc.insert()
	return {"version": doc.layout_version, "modified": str(doc.modified)}
