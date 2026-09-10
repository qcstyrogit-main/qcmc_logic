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
		{"label": _("Sales Order"), "fieldname": "sales_order", "fieldtype": "Link", "options": "Sales Order", "width": 150},
		{"label": _("Customer"), "fieldname": "customer_name", "fieldtype": "Data", "width": 210},
		{"label": _("Item Code"), "fieldname": "item_code", "fieldtype": "Link", "options": "Item", "width": 150},
		{"label": _("Item Name"), "fieldname": "item_name", "fieldtype": "Data", "width": 210},
		{"label": _("Warehouse"), "fieldname": "warehouse", "fieldtype": "Link", "options": "Warehouse", "width": 180},
		{"label": _("DR Qty"), "fieldname": "qty", "fieldtype": "Float", "width": 100},
		{"label": _("SO Qty"), "fieldname": "so_qty", "fieldtype": "Float", "width": 100},
		{"label": _("Delivered Qty"), "fieldname": "delivered_qty", "fieldtype": "Float", "width": 110},
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
			dni.against_sales_order AS sales_order, dn.customer_name,
			dni.item_code, dni.item_name, dni.warehouse, dni.qty,
			soi.qty AS so_qty, soi.delivered_qty, IFNULL(bin.actual_qty, 0) AS actual_qty,
			soi.delivery_date
		FROM `tabDelivery Note` dn
		JOIN `tabDelivery Note Item` dni ON dni.parent = dn.name
		JOIN `tabSales Order Item` soi ON soi.name = dni.so_detail
		LEFT JOIN `tabBin` bin ON bin.item_code = dni.item_code AND bin.warehouse = dni.warehouse
		WHERE dn.docstatus = 0
			AND dn.workflow_state = 'For Stock Confirmation'
			AND {conditions}
		ORDER BY soi.delivery_date, dn.name, dni.idx
	""".format(conditions=" AND ".join(conditions)), values, as_dict=True)

	return columns, rows, _("{0} item(s) awaiting stock confirmation.").format(len(rows)), None, [
		{"value": len({row.delivery_note for row in rows}), "indicator": "Orange", "label": _("Delivery Notes"), "datatype": "Int"},
		{"value": len(rows), "indicator": "Blue", "label": _("Items"), "datatype": "Int"},
	]


@frappe.whitelist()
def confirm_delivery_notes(delivery_notes, remarks=None):
	names = list(dict.fromkeys(frappe.parse_json(delivery_notes)))
	if not names:
		frappe.throw(_("Select at least one Delivery Note."))
	for name in names:
		doc = frappe.get_doc("Delivery Note", name)
		_validate_delivery_note(doc, require_transact=True)
		doc.add_comment("Info", _("Stock Confirmation: OK{0}").format(_remarks_suffix(remarks)))
		doc.workflow_state = "For DR Printing"
		doc.status = "For DR Printing"
		doc.save(ignore_permissions=True)
		doc.add_comment("Workflow", _("For DR Printing"))
	return _("Moved Delivery Note(s) to For DR Printing: {0}").format(", ".join(names))


@frappe.whitelist()
def adjust_item_quantity(dn_detail, qty, scheduling_date, remarks=None):
	parent = frappe.db.get_value("Delivery Note Item", dn_detail, "parent")
	if not parent:
		frappe.throw(_("Delivery Note Item {0} was not found.").format(dn_detail))
	doc = frappe.get_doc("Delivery Note", parent)
	_validate_delivery_note(doc, require_transact=True)
	item = next((row for row in doc.items if row.name == dn_detail), None)
	new_qty = frappe.utils.flt(qty)
	if not item or new_qty <= 0 or new_qty >= frappe.utils.flt(item.qty):
		frappe.throw(_("New quantity must be greater than zero and less than the current DR quantity."))
	old_qty = item.qty
	item.qty = new_qty
	item.amount = new_qty * item.rate
	item.base_amount = new_qty * item.base_rate
	doc.save(ignore_permissions=True)
	_set_next_scheduling_date([item], scheduling_date, parent, "SA")
	doc.add_comment(
		"Edit",
		_("Stock Confirmation: SA - {0} quantity reduced from {1} to {2}{3}").format(
			frappe.bold(item.item_code), old_qty, new_qty, _remarks_suffix(remarks)
		),
	)
	return _("Updated {0}. The remaining quantity is available for rescheduling.").format(parent)


@frappe.whitelist()
def remove_items(dn_details, scheduling_date, reason_code="SA", remarks=None):
	details = list(dict.fromkeys(frappe.parse_json(dn_details)))
	if not details:
		frappe.throw(_("Select at least one Delivery Note item."))
	grouped = {}
	for detail in details:
		parent = frappe.db.get_value("Delivery Note Item", detail, "parent")
		if not parent:
			frappe.throw(_("Delivery Note Item {0} was not found.").format(detail))
		grouped.setdefault(parent, []).append(detail)

	for parent, selected in grouped.items():
		doc = frappe.get_doc("Delivery Note", parent)
		_validate_delivery_note(doc, require_transact=True)
		removed = [row for row in doc.items if row.name in selected]
		if len(removed) != len(selected):
			frappe.throw(_("One or more selected items no longer belong to {0}.").format(parent))
		for item in removed:
			doc.remove(item)
		_set_next_scheduling_date(removed, scheduling_date, parent, reason_code)
		message = _("Stock Confirmation: {0} - Removed unavailable item(s): {1}{2}").format(
			reason_code,
			", ".join(frappe.bold(item.item_code) for item in removed),
			_remarks_suffix(remarks),
		)
		if doc.items:
			doc.save(ignore_permissions=True)
			doc.add_comment("Edit", message)
		else:
			for sales_order in {item.against_sales_order for item in removed if item.against_sales_order}:
				frappe.get_doc("Sales Order", sales_order).add_comment("Info", _("{0} (Delivery Note {1})").format(message, parent))
			frappe.delete_doc("Delivery Note", parent, ignore_permissions=True)
	return _("Removed selected item(s). Released quantities are available for rescheduling.")


def _validate_delivery_note(doc, require_transact=False):
	if doc.docstatus != 0 or doc.workflow_state != "For Stock Confirmation":
		frappe.throw(_("Delivery Note {0} is no longer awaiting stock confirmation.").format(doc.name))
	_validate_logistics_role()
	for item in doc.items:
		_validate_warehouse_access(item.warehouse, require_transact=require_transact)


def _validate_logistics_role():
	roles = set(frappe.get_roles(frappe.session.user))
	if frappe.session.user != "Administrator" and "Stock Confirm User" not in roles:
		frappe.throw(_("You are not allowed to perform stock confirmation."), frappe.PermissionError)


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


def _remarks_suffix(remarks):
	return " - " + frappe.utils.escape_html(remarks) if remarks else ""


def _set_next_scheduling_date(items, scheduling_date, delivery_note, reason_code):
	if not scheduling_date:
		frappe.throw(_("The report delivery date is required for rescheduling."))
	next_date = frappe.utils.add_days(frappe.utils.getdate(scheduling_date), 1)
	grouped = {}
	for item in items:
		if item.so_detail and item.against_sales_order:
			grouped.setdefault(item.against_sales_order, []).append(item)

	for sales_order, linked_items in grouped.items():
		before_doc = frappe.get_doc("Sales Order", sales_order)
		for item in linked_items:
			current = frappe.db.get_value(
				"Sales Order Item", item.so_detail, "custom_next_scheduling_date"
			)
			deferred_until = max(frappe.utils.getdate(current), next_date) if current else next_date
			frappe.db.set_value(
				"Sales Order Item", item.so_detail, "custom_next_scheduling_date", deferred_until
			)
		after_doc = frappe.get_doc("Sales Order", sales_order)
		version = frappe.new_doc("Version")
		if version.update_version_info(before_doc, after_doc):
			version.insert(ignore_permissions=True)
		after_doc.add_comment(
			"Info",
			_("Stock Confirmation {0} from Delivery Note {1}: released item(s) {2} return to scheduling on {3}.").format(
				reason_code,
				delivery_note,
				", ".join(frappe.bold(item.item_code) for item in linked_items),
				frappe.utils.formatdate(next_date),
			),
		)
