import frappe
from frappe import _

from qcmc_logic.customs.territory_access_permissions import (
	get_user_allowed_territories,
	has_territory_access,
)
from qcmc_logic.utils import (
	_get_effective_warehouse_access_names,
	get_user_allowed_warehouses,
)


def execute(filters=None):
	filters = frappe._dict(filters or {})
	columns = [
		{"label": _("Sales Order"), "fieldname": "sales_order", "fieldtype": "Link", "options": "Sales Order", "width": 150},
		{"label": _("Customer"), "fieldname": "customer_name", "fieldtype": "Data", "width": 220},
		{"label": _("SO Type"), "fieldname": "so_type", "fieldtype": "Data", "width": 110},
		{"label": _("Item Code"), "fieldname": "item_code", "fieldtype": "Link", "options": "Item", "width": 150},
		{"label": _("Item Name"), "fieldname": "item_name", "fieldtype": "Data", "width": 220},
		{"label": _("Warehouse"), "fieldname": "warehouse", "fieldtype": "Link", "options": "Warehouse", "width": 180},
		{"label": _("Ordered Qty"), "fieldname": "qty", "fieldtype": "Float", "width": 110},
		{"label": _("Delivered Qty"), "fieldname": "delivered_qty", "fieldtype": "Float", "width": 110},
		{"label": _("Balance Qty"), "fieldname": "balance_qty", "fieldtype": "Float", "width": 110},
		{"label": _("Active DR Qty"), "fieldname": "draft_dr_qty", "fieldtype": "Float", "width": 110},
		{"label": _("Available Qty"), "fieldname": "available_qty", "fieldtype": "Float", "width": 110},
		{"label": _("Warehouse Stock"), "fieldname": "actual_qty", "fieldtype": "Float", "width": 120},
		{"label": _("Original Delivery Date(s)"), "fieldname": "delivery_dates", "fieldtype": "Data", "width": 170},
		{"label": _("Available From"), "fieldname": "available_from", "fieldtype": "Date", "width": 120},
	]
	if not filters.get("delivery_date") or not filters.get("company"):
		return columns, [], _("Select a company and delivery date to view eligible Sales Orders."), None, []
	conditions = ["so.company = %(company)s"]
	values = {"delivery_date": filters.delivery_date, "company": filters.company}
	if filters.get("warehouse"):
		conditions.append("soi.warehouse = %(warehouse)s")
		values["warehouse"] = filters.warehouse
	_apply_sales_coordinator_scope(conditions, values)
	rows = frappe.db.sql("""
		SELECT soi.name AS so_detail, so.name AS sales_order, so.customer_name,
			so.custom_so_type AS so_type, soi.item_code, soi.item_name, soi.warehouse,
			soi.qty, soi.delivered_qty, (soi.qty - soi.delivered_qty) AS balance_qty,
			IFNULL(draft_dr.qty, 0) AS draft_dr_qty,
			(soi.qty - soi.delivered_qty - IFNULL(draft_dr.qty, 0)) AS available_qty,
			IFNULL(bin.actual_qty, 0) AS actual_qty,
			soi.delivery_date,
			COALESCE(soi.custom_next_scheduling_date, soi.delivery_date) AS available_from
		FROM `tabSales Order` so
		JOIN `tabSales Order Item` soi ON soi.parent = so.name
		JOIN `tabWarehouse` wh ON wh.name = soi.warehouse
		LEFT JOIN `tabBin` bin ON bin.item_code = soi.item_code AND bin.warehouse = soi.warehouse
		LEFT JOIN (
			SELECT dni.so_detail, SUM(dni.qty) AS qty
			FROM `tabDelivery Note Item` dni
			JOIN `tabDelivery Note` dn ON dn.name = dni.parent
			WHERE dn.docstatus = 0
			GROUP BY dni.so_detail
		) draft_dr ON draft_dr.so_detail = soi.name
		WHERE so.docstatus = 1 AND so.status = 'To Deliver and Bill'
			AND so.custom_so_type IN ('FOB', 'FOB-DIRECT', 'REGULAR')
			AND IFNULL(wh.custom_is_province, 0) = 0
			AND (soi.qty - soi.delivered_qty - IFNULL(draft_dr.qty, 0)) > 0
			AND COALESCE(soi.custom_next_scheduling_date, soi.delivery_date) <= %(delivery_date)s
			AND {conditions}
		ORDER BY available_from, so.name, soi.idx
	""".format(conditions=" AND ".join(conditions)), values, as_dict=True)
	rows = _consolidate_rows(rows)
	return columns, rows, _("{0} eligible item(s) found.").format(len(rows)), None, [
		{"value": len({row.sales_order for row in rows}), "indicator": "Blue", "label": _("Sales Orders"), "datatype": "Int"},
		{"value": len(rows), "indicator": "Green", "label": _("Items"), "datatype": "Int"},
	]


def _consolidate_rows(rows):
	consolidated = {}
	for row in rows:
		key = (row.sales_order, row.item_code, row.warehouse)
		if key not in consolidated:
			consolidated[key] = frappe._dict(row)
			consolidated[key].so_details = [row.so_detail]
			consolidated[key].delivery_dates = {str(row.delivery_date)}
			continue
		target = consolidated[key]
		target.so_details.append(row.so_detail)
		target.delivery_dates.add(str(row.delivery_date))
		for fieldname in ("qty", "delivered_qty", "balance_qty", "draft_dr_qty", "available_qty"):
			target[fieldname] = frappe.utils.flt(target[fieldname]) + frappe.utils.flt(row[fieldname])
		target.available_from = max(target.available_from, row.available_from)

	for row in consolidated.values():
		row.delivery_dates = ", ".join(sorted(row.delivery_dates))
	return list(consolidated.values())


@frappe.whitelist()
def update_delivery_dates(so_details, delivery_date):
	so_details = frappe.parse_json(so_details)
	if not so_details or not delivery_date:
		frappe.throw(_("Items and a new delivery date are required."))
	before_docs = {}
	changes = {}
	for detail in so_details:
		row = frappe.db.get_value("Sales Order Item", detail, ["parent", "delivery_date"], as_dict=True)
		if not row:
			frappe.throw(_("Sales Order Item {0} was not found.").format(detail))
		so = frappe.get_doc("Sales Order", row.parent)
		if so.docstatus != 1 or so.status != "To Deliver and Bill" or so.custom_so_type not in ("FOB", "FOB-DIRECT", "REGULAR"):
			frappe.throw(_("Sales Order {0} is not eligible for scheduling.").format(row.parent))
		item = next((item for item in so.items if item.name == detail), None)
		if not item or item.qty <= item.delivered_qty:
			frappe.throw(_("Sales Order Item {0} has no undelivered quantity.").format(detail))
		if item.warehouse and frappe.db.get_value("Warehouse", item.warehouse, "custom_is_province"):
			frappe.throw(_("Sales Order Item {0} belongs to a provincial warehouse.").format(detail))
		_validate_sales_coordinator_access(so, item, require_transact=True)
		if str(row.delivery_date or "") == str(delivery_date):
			continue
		before_docs.setdefault(row.parent, so)
		changes.setdefault(row.parent, []).append(
			{"item_code": item.item_code, "old_date": row.delivery_date, "new_date": delivery_date}
		)
		frappe.db.set_value("Sales Order Item", detail, "delivery_date", delivery_date)
		frappe.db.set_value("Sales Order Item", detail, "custom_next_scheduling_date", None)
	for sales_order, sales_order_changes in changes.items():
		_record_delivery_date_history(
			before_docs[sales_order],
			frappe.get_doc("Sales Order", sales_order),
			sales_order_changes,
		)
	frappe.db.commit()
	return _("Delivery dates updated and recorded in Sales Order history. The report has been refreshed.")


def _record_delivery_date_history(before_doc, after_doc, changes):
	version = frappe.new_doc("Version")
	if version.update_version_info(before_doc, after_doc):
		version.insert(ignore_permissions=True)

	lines = [_("Delivery dates changed from Sales Order Delivery Scheduling:")]
	for change in changes:
		lines.append(
			_("{0}: {1} to {2}").format(
				frappe.bold(change["item_code"]),
				frappe.utils.formatdate(change["old_date"]),
				frappe.utils.formatdate(change["new_date"]),
			)
		)
	after_doc.add_comment("Edit", "<br>".join(lines))


@frappe.whitelist()
def create_delivery_notes(so_details):
	so_details = list(dict.fromkeys(frappe.parse_json(so_details)))
	if not so_details:
		frappe.throw(_("Select at least one Sales Order item."))

	details_by_sales_order = {}
	for detail in so_details:
		row = frappe.db.get_value("Sales Order Item", detail, ["parent"], as_dict=True)
		if not row:
			frappe.throw(_("Sales Order Item {0} was not found.").format(detail))
		details_by_sales_order.setdefault(row.parent, []).append(detail)

	created = []
	from erpnext.selling.doctype.sales_order.sales_order import make_delivery_note
	for name, selected_details in details_by_sales_order.items():
		so = frappe.get_doc("Sales Order", name)
		available_qty = _validate_sales_order(so, selected_details)
		dn = make_delivery_note(name, kwargs={"filtered_children": selected_details})
		if not dn or not dn.get("items"):
			frappe.throw(_("No selected undelivered items are available for Sales Order {0}.").format(name))
		for item in dn.items:
			item.qty = available_qty[item.so_detail]
			item.amount = item.qty * item.rate
			item.base_amount = item.qty * item.base_rate
		dn.run_method("calculate_taxes_and_totals")
		from erpnext.stock.doctype.packed_item.packed_item import make_packing_list
		make_packing_list(dn)
		dn.custom_sales_order = name
		dn.workflow_state = "Draft"
		dn.insert(ignore_permissions=True)
		dn.db_set("workflow_state", "For Stock Confirmation")
		created.append(dn.name)
	return _("Created Delivery Note(s): {0}").format(", ".join(created))


def _validate_sales_order(so, selected_details):
	if so.docstatus != 1 or so.status != "To Deliver and Bill":
		frappe.throw(_("Sales Order {0} is not in To Deliver and Bill status.").format(so.name))
	if so.custom_so_type not in ("FOB", "FOB-DIRECT", "REGULAR"):
		frappe.throw(_("Sales Order {0} has an unsupported SO Type.").format(so.name))
	items = {item.name: item for item in so.items}
	available_qty = {}
	for detail in selected_details:
		item = items.get(detail)
		if not item:
			frappe.throw(_("Sales Order Item {0} does not belong to Sales Order {1}.").format(detail, so.name))
		if item.qty <= item.delivered_qty:
			frappe.throw(_("Sales Order Item {0} has no undelivered quantity.").format(detail))
		if item.warehouse and frappe.db.get_value("Warehouse", item.warehouse, "custom_is_province"):
			frappe.throw(_("Sales Order Item {0} belongs to provincial warehouse {1}.").format(detail, item.warehouse))
		_validate_sales_coordinator_access(so, item, require_transact=True)
		draft_qty = frappe.db.sql("""
			SELECT IFNULL(SUM(dni.qty), 0)
			FROM `tabDelivery Note Item` dni
			JOIN `tabDelivery Note` dn ON dn.name = dni.parent
			WHERE dni.so_detail = %s AND dn.docstatus = 0
		""", detail)[0][0]
		available = frappe.utils.flt(item.qty) - frappe.utils.flt(item.delivered_qty) - frappe.utils.flt(draft_qty)
		if available <= 0:
			frappe.throw(_("Sales Order Item {0} has no quantity available for another Delivery Note.").format(detail))
		available_qty[detail] = available
	return available_qty


def _is_sales_coordinator():
	return "Sales Coordinator" in frappe.get_roles(frappe.session.user)


def _apply_sales_coordinator_scope(conditions, values):
	if not _is_sales_coordinator():
		return

	user = frappe.session.user
	if has_territory_access(user):
		territories = get_user_allowed_territories(user)
		if not territories:
			conditions.append("1 = 0")
		else:
			conditions.append("so.territory IN %(allowed_territories)s")
			values["allowed_territories"] = tuple(territories)

	if _get_effective_warehouse_access_names(user, source="Role Profile"):
		warehouses = get_user_allowed_warehouses(
			user, require_list_view=True, source="Role Profile"
		)
		if not warehouses:
			conditions.append("1 = 0")
		else:
			conditions.append("soi.warehouse IN %(allowed_warehouses)s")
			values["allowed_warehouses"] = tuple(warehouses)


def _validate_sales_coordinator_access(so, item, require_transact=False):
	if not _is_sales_coordinator():
		return

	user = frappe.session.user
	if has_territory_access(user):
		territories = set(
			get_user_allowed_territories(user, require_transactions=require_transact)
		)
		if not so.territory or so.territory not in territories:
			frappe.throw(_("You are not allowed to transact in territory {0}.").format(so.territory), frappe.PermissionError)

	if _get_effective_warehouse_access_names(user, source="Role Profile"):
		warehouses = set(
			get_user_allowed_warehouses(
				user,
				require_transact=require_transact,
				require_list_view=not require_transact,
				source="Role Profile",
			)
		)
		if not item.warehouse or item.warehouse not in warehouses:
			frappe.throw(_("You are not allowed to transact in warehouse {0}.").format(item.warehouse), frappe.PermissionError)
