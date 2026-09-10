import frappe
from frappe import _

from qcmc_logic.utils import (
	_get_effective_warehouse_access_names,
	get_user_allowed_warehouses,
)


def execute(filters=None):
	filters = frappe._dict(filters or {})
	columns = [
		{"label": _("Delivery Note"), "fieldname": "delivery_note", "fieldtype": "Link", "options": "Delivery Note", "width": 160},
		{"label": _("DR Number"), "fieldname": "dr_number", "fieldtype": "Data", "width": 120},
		{"label": _("Sales Order"), "fieldname": "sales_order", "fieldtype": "Link", "options": "Sales Order", "width": 150},
		{"label": _("Customer"), "fieldname": "customer_name", "fieldtype": "Data", "width": 210},
		{"label": _("Item Code"), "fieldname": "item_code", "fieldtype": "Link", "options": "Item", "width": 150},
		{"label": _("Item Name"), "fieldname": "item_name", "fieldtype": "Data", "width": 210},
		{"label": _("Warehouse"), "fieldname": "warehouse", "fieldtype": "Link", "options": "Warehouse", "width": 180},
		{"label": _("Qty"), "fieldname": "qty", "fieldtype": "Float", "width": 90},
		{"label": _("Warehouse Stock"), "fieldname": "actual_qty", "fieldtype": "Float", "width": 120},
		{"label": _("Scheduled Date"), "fieldname": "delivery_date", "fieldtype": "Date", "width": 125},
	]
	if not filters.get("company") or not filters.get("delivery_date"):
		return columns, [], _("Select a company and delivery date."), None, []

	conditions = ["dn.company = %(company)s", "soi.delivery_date <= %(delivery_date)s"]
	values = {"company": filters.company, "delivery_date": filters.delivery_date}
	if filters.get("warehouse"):
		conditions.append("dni.warehouse = %(warehouse)s")
		values["warehouse"] = filters.warehouse
	_apply_warehouse_scope(conditions, values)

	rows = frappe.db.sql("""
		SELECT dni.name AS dn_detail, dn.name AS delivery_note,
			dn.custom_dr_number AS dr_number, dni.against_sales_order AS sales_order,
			dn.customer_name, dni.item_code, dni.item_name, dni.warehouse, dni.qty,
			IFNULL(bin.actual_qty, 0) AS actual_qty, soi.delivery_date
		FROM `tabDelivery Note` dn
		JOIN `tabDelivery Note Item` dni ON dni.parent = dn.name
		JOIN `tabSales Order Item` soi ON soi.name = dni.so_detail
		JOIN `tabWarehouse` wh ON wh.name = dni.warehouse
		LEFT JOIN `tabBin` bin ON bin.item_code = dni.item_code AND bin.warehouse = dni.warehouse
		WHERE dn.docstatus = 0
			AND dn.workflow_state = 'For DR Printing'
			AND IFNULL(wh.custom_is_province, 0) = 0
			AND {conditions}
		ORDER BY soi.delivery_date, dn.name, dni.idx
	""".format(conditions=" AND ".join(conditions)), values, as_dict=True)

	return columns, rows, _("{0} item(s) ready for DR printing.").format(len(rows)), None, [
		{"value": len({row.delivery_note for row in rows}), "indicator": "Orange", "label": _("Delivery Notes"), "datatype": "Int"},
		{"value": len({row.delivery_note for row in rows if row.dr_number}), "indicator": "Green", "label": _("Numbered"), "datatype": "Int"},
	]


@frappe.whitelist()
def assign_dr_number(delivery_note, dr_number):
	_validate_invoicing_role()
	dr_number = (dr_number or "").strip()
	if not dr_number:
		frappe.throw(_("DR Number is required."))

	# Serializes assignment of the same DR number across concurrent clerk sessions.
	with frappe.cache.lock("delivery-note-dr-number:{0}".format(dr_number), timeout=15):
		doc = _get_locked_delivery_note(delivery_note)
		_validate_delivery_note(doc, require_transact=True)
		duplicate = frappe.db.get_value(
			"Delivery Note",
			{"custom_dr_number": dr_number, "name": ["!=", doc.name], "docstatus": ["!=", 2]},
			"name",
		)
		if duplicate:
			frappe.throw(_("DR Number {0} is already assigned to Delivery Note {1}.").format(
				frappe.bold(dr_number), frappe.bold(duplicate)
			))
		doc.custom_dr_number = dr_number
		doc.save(ignore_permissions=True)
		doc.add_comment("Edit", _("Assigned DR Number {0} for printing.").format(frappe.bold(dr_number)))

	return {
		"delivery_note": doc.name,
		"dr_number": dr_number,
		"print_format": _get_print_format(doc.company),
	}


@frappe.whitelist()
def submit_for_delivery(delivery_notes):
	_validate_invoicing_role()
	names = list(dict.fromkeys(frappe.parse_json(delivery_notes)))
	if not names:
		frappe.throw(_("Select at least one Delivery Note."))

	for name in sorted(names):
		doc = _get_locked_delivery_note(name)
		_validate_delivery_note(doc, require_transact=True)
		if not doc.custom_dr_number:
			frappe.throw(_("Assign and print a DR Number for Delivery Note {0} first.").format(frappe.bold(name)))
		doc.workflow_state = "To Deliver and Bill"
		doc.status = "To Deliver and Bill"
		doc.save(ignore_permissions=True)
		doc.add_comment("Workflow", _("Submit for Delivery"))

	return _("Submitted Delivery Note(s) for delivery: {0}").format(", ".join(names))


def _get_locked_delivery_note(name):
	locked_name = frappe.db.sql(
		"SELECT name FROM `tabDelivery Note` WHERE name = %s FOR UPDATE", (name,)
	)
	if not locked_name:
		frappe.throw(_("Delivery Note {0} was not found.").format(name))
	return frappe.get_doc("Delivery Note", name)


def _validate_delivery_note(doc, require_transact=False):
	if doc.docstatus != 0 or doc.workflow_state != "For DR Printing":
		frappe.throw(_("Delivery Note {0} is no longer awaiting DR printing.").format(doc.name))
	for item in doc.items:
		_validate_warehouse_access(item.warehouse, require_transact=require_transact)


def _validate_invoicing_role():
	roles = set(frappe.get_roles(frappe.session.user))
	if frappe.session.user != "Administrator" and "Invoicing Clerk" not in roles:
		frappe.throw(_("You are not allowed to assign or submit Delivery Receipts."), frappe.PermissionError)


def _apply_warehouse_scope(conditions, values):
	user = frappe.session.user
	if not _get_effective_warehouse_access_names(user, source="Role Profile"):
		return
	warehouses = get_user_allowed_warehouses(user, require_list_view=True, source="Role Profile")
	if not warehouses:
		conditions.append("1 = 0")
	else:
		conditions.append("dni.warehouse IN %(allowed_warehouses)s")
		values["allowed_warehouses"] = tuple(warehouses)


def _validate_warehouse_access(warehouse, require_transact=False):
	user = frappe.session.user
	if not _get_effective_warehouse_access_names(user, source="Role Profile"):
		return
	allowed = set(get_user_allowed_warehouses(
		user,
		require_transact=require_transact,
		require_list_view=not require_transact,
		source="Role Profile",
	))
	if not warehouse or warehouse not in allowed:
		frappe.throw(_("You are not allowed to transact in warehouse {0}.").format(warehouse), frappe.PermissionError)


def _get_print_format(company):
	formats = {
		"QC Styropackaging Corporation": "Deliver Receipt QC",
		"Multiplast Corporation": "Delivery Receipt MC",
	}
	return formats.get(company) or frappe.get_meta("Delivery Note").default_print_format or "Standard"
