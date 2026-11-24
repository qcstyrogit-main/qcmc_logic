"""Shared Delivery Schedule workbench query and transaction services."""

import frappe
from frappe import _

from qcmc_logic.utils import (
	_get_effective_warehouse_access_names,
	get_user_allowed_warehouses,
)

DEFAULT_LOGISTICS_REASON_CODES = {
	"OK": "Good to go",
	"TO": "Truck Overload",
	"CR": "Customer Request",
	"SA": "Stock Availability",
	"OR": "Off Route",
	"ND": "Next Delivery Date",
	"SE": "Sales Error",
}


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
		{"label": _("Proposed Qty"), "fieldname": "logistics_proposed_qty", "fieldtype": "Float", "width": 115},
		{"label": _("Proposed Date"), "fieldname": "logistics_proposed_date", "fieldtype": "Date", "width": 115},
		{"label": _("Logistics Reason"), "fieldname": "logistics_reason", "fieldtype": "Data", "width": 180},
		{"label": _("Logistics Remarks"), "fieldname": "logistics_remarks", "fieldtype": "Data", "width": 220},
	]
	if not filters.get("company") or not filters.get("delivery_date"):
		return columns, [], _("Select a company and delivery date."), None, []

	conditions = ["dn.company = %(company)s", "((dni.custom_so_delivery_schedule IS NULL AND soi.delivery_date <= %(delivery_date)s) OR (dni.custom_so_delivery_schedule IS NOT NULL AND operational_schedule.delivery_date <= %(delivery_date)s))"]
	values = {"company": filters.company, "delivery_date": filters.delivery_date}
	if filters.get("warehouse"):
		conditions.append("dni.warehouse = %(warehouse)s")
		values["warehouse"] = filters.warehouse
	_apply_warehouse_scope(conditions, values)
	logistics_reason_sql = "dni.custom_logistics_reason" if frappe.db.has_column("Delivery Note Item", "custom_logistics_reason") else "''"
	logistics_remarks_sql = "dni.custom_logistics_remarks" if frappe.db.has_column("Delivery Note Item", "custom_logistics_remarks") else "''"
	logistics_proposed_qty_sql = "CASE WHEN IFNULL(dni.custom_logistics_reason, '') = '' AND IFNULL(dni.custom_logistics_remarks, '') = '' AND dni.custom_logistics_proposed_date IS NULL THEN NULL WHEN IFNULL(dni.custom_logistics_reason, '') = 'OK' AND IFNULL(dni.custom_logistics_proposed_qty, 0) = 0 THEN NULL ELSE dni.custom_logistics_proposed_qty END" if frappe.db.has_column("Delivery Note Item", "custom_logistics_proposed_qty") else "NULL"
	logistics_proposed_date_sql = "dni.custom_logistics_proposed_date" if frappe.db.has_column("Delivery Note Item", "custom_logistics_proposed_date") else "NULL"

	rows = frappe.db.sql("""
		SELECT dni.name AS dn_detail, dn.name AS delivery_note,
			(SELECT COUNT(*) FROM `tabDelivery Note Item` all_items WHERE all_items.parent = dn.name) AS dn_item_count,
			dni.against_sales_order AS sales_order, dn.customer_name,
			dni.item_code, dni.item_name, dni.warehouse, dni.qty,
			soi.qty AS so_qty, soi.delivered_qty, IFNULL(bin.actual_qty, 0) AS actual_qty,
			COALESCE(operational_schedule.delivery_date, soi.delivery_date) AS delivery_date,
		dni.custom_so_delivery_schedule AS schedule_id,
		{logistics_proposed_qty_sql} AS logistics_proposed_qty,
			{logistics_proposed_date_sql} AS logistics_proposed_date,
			{logistics_reason_sql} AS logistics_reason,
			{logistics_remarks_sql} AS logistics_remarks
		FROM `tabDelivery Note` dn
		JOIN `tabDelivery Note Item` dni ON dni.parent = dn.name
		JOIN `tabSales Order Item` soi ON soi.name = dni.so_detail
		LEFT JOIN `tabSO Delivery Schedule` operational_schedule ON operational_schedule.name = dni.custom_so_delivery_schedule
		LEFT JOIN `tabBin` bin ON bin.item_code = dni.item_code AND bin.warehouse = dni.warehouse
		WHERE dn.docstatus = 0
			AND dn.workflow_state = 'For Stock Confirmation'
			AND {conditions}
		ORDER BY delivery_date, dn.name, dni.idx
	""".format(
		conditions=" AND ".join(conditions),
		logistics_reason_sql=logistics_reason_sql,
		logistics_remarks_sql=logistics_remarks_sql,
		logistics_proposed_qty_sql=logistics_proposed_qty_sql,
		logistics_proposed_date_sql=logistics_proposed_date_sql,
	), values, as_dict=True)

	return columns, rows, _("{0} item(s) awaiting stock confirmation.").format(len(rows)), None, [
		{"value": len({row.delivery_note for row in rows}), "indicator": "Orange", "label": _("Delivery Notes"), "datatype": "Int"},
		{"value": len(rows), "indicator": "Blue", "label": _("Items"), "datatype": "Int"},
	]


@frappe.whitelist()
def confirm_delivery_notes(delivery_notes, reason_code=None, remarks=None):
	names = list(dict.fromkeys(frappe.parse_json(delivery_notes)))
	if not names:
		frappe.throw(_("Select at least one Delivery Note."))
	for name in names:
		doc = frappe.get_doc("Delivery Note", name)
		_validate_delivery_note(doc, require_transact=True)
		doc.add_comment("Info", _("Logistics reviewed. Sales approval is required before DR printing.{0}").format(_remarks_suffix(remarks)))
	return _("Saved logistics review for Delivery Note(s): {0}. Sales must proceed to DR printing.").format(", ".join(names))


@frappe.whitelist()
def get_delivery_note_items(delivery_note):
	return get_delivery_note_items_bulk([delivery_note])


@frappe.whitelist()
def get_delivery_note_items_bulk(delivery_notes):
	names = _parse_names(delivery_notes)
	rows = []
	for name in names:
		doc = frappe.get_doc("Delivery Note", name)
		_validate_delivery_note(doc, require_transact=True)
		for item in doc.items:
			rows.append(_serialize_logistics_item(item, doc))
	return rows


@frappe.whitelist()
def save_logistics_remarks(delivery_note, items):
	parsed_items = frappe.parse_json(items or "[]")
	for row in parsed_items:
		row["delivery_note"] = delivery_note
	return save_logistics_remarks_bulk(parsed_items)


@frappe.whitelist()
def save_logistics_remarks_bulk(items):
	parsed_items = frappe.parse_json(items or "[]")
	grouped = {}
	for row in parsed_items:
		delivery_note = row.get("delivery_note")
		dn_detail = row.get("dn_detail")
		if delivery_note and dn_detail:
			grouped.setdefault(delivery_note, {})[dn_detail] = row
	if not grouped:
		frappe.throw(_("Enter logistics remarks for at least one item."))

	saved = []
	for delivery_note, item_values in grouped.items():
		doc = frappe.get_doc("Delivery Note", delivery_note)
		_validate_delivery_note(doc, require_transact=True)
		changed = False
		for item in doc.items:
			values = item_values.get(item.name)
			if not values:
				continue
			reason_code = values.get("logistics_reason") or ""
			if reason_code:
				_validate_reason_code(reason_code)
			_set_logistics_recommendation_fields(
				item,
				reason_code,
				values.get("logistics_remarks"),
				values.get("logistics_proposed_qty"),
				values.get("logistics_proposed_date"),
			)
			changed = True
		if changed:
			doc.save(ignore_permissions=True)
			doc.add_comment("Info", _("Logistics Remarks saved. Sales approval is required before DR printing."))
			saved.append(doc.name)
	if not saved:
		frappe.throw(_("No matching Delivery Note items were found to update."))
	return _("Saved Logistics Remarks for {0} Delivery Note(s): {1}.").format(len(saved), ", ".join(saved))


@frappe.whitelist()
def get_dr_printing_review_items(delivery_note):
	return get_dr_printing_review_items_bulk([delivery_note])


@frappe.whitelist()
def get_dr_printing_review_items_bulk(delivery_notes):
	_validate_sales_approval_role()
	names = _parse_names(delivery_notes)
	rows = []
	for name in names:
		doc = _get_locked_delivery_note(name)
		_validate_sales_review_delivery_note(doc, require_transact=True)
		for item in doc.items:
			rows.append(_serialize_review_item(item, doc))
	return rows


@frappe.whitelist()
def proceed_to_dr_printing(delivery_note, items):
	parsed_items = frappe.parse_json(items or "[]")
	for row in parsed_items:
		row["delivery_note"] = delivery_note
	return proceed_to_dr_printing_bulk(parsed_items)


@frappe.whitelist()
def proceed_to_dr_printing_bulk(items):
	_validate_sales_approval_role()
	parsed_items = frappe.parse_json(items or "[]")
	grouped = {}
	for row in parsed_items:
		delivery_note = row.get("delivery_note")
		dn_detail = row.get("dn_detail")
		if delivery_note and dn_detail:
			grouped.setdefault(delivery_note, {})[dn_detail] = row
	if not grouped:
		frappe.throw(_("Review at least one Delivery Note item."))

	approved = []
	for delivery_note, decisions in grouped.items():
		_approve_delivery_note_for_dr(delivery_note, decisions)
		approved.append(delivery_note)
	return _("Delivery Note(s) now For DR Printing: {0}.").format(", ".join(approved))


def _approve_delivery_note_for_dr(delivery_note, decisions):
	doc = _get_locked_delivery_note(delivery_note)
	_validate_sales_review_delivery_note(doc, require_transact=True)
	doc.check_permission("write")

	if set(decisions) != {item.name for item in doc.items}:
		frappe.throw(_("Select and review every item in Delivery Note {0} before proceeding. Clear filters if items are hidden.").format(doc.name))
	if not doc.items:
		frappe.throw(_("A Delivery Note cannot proceed with no items."))
	before = _delivery_note_transition_snapshot(doc)
	for item in doc.items:
		version = decisions[item.name].get("document_modified")
		if version and version != str(doc.modified):
			frappe.throw(_("Delivery Note {0} changed. Refresh and review it again before proceeding.").format(doc.name))
		_validate_saved_logistics_commitment(item)
		committed_qty = _get_logistics_committed_qty(item)
		if frappe.utils.flt(item.qty) <= 0 or frappe.utils.flt(item.qty) > committed_qty:
			frappe.throw(_("Complete the Sales quantity revision for {0} before proceeding. Current DR quantity must be positive and no greater than Logistics commitment.").format(frappe.bold(item.item_code)))
		if item.get("custom_sales_final_qty") not in (None, "") and frappe.utils.flt(item.custom_sales_final_qty) != frappe.utils.flt(item.qty):
			frappe.throw(_("Sales final quantity for {0} does not match its saved DR quantity. Apply Change DR Qty before proceeding.").format(frappe.bold(item.item_code)))
		if not item.get("so_detail") or not item.get("against_sales_order"):
			frappe.throw(_("Delivery Note item {0} is missing its Sales Order schedule reference.").format(frappe.bold(item.item_code)))
		source = frappe.get_doc("Sales Order Item", item.so_detail)
		if source.parent != item.against_sales_order:
			frappe.throw(_("Delivery Note item {0} references a schedule from a different Sales Order.").format(frappe.bold(item.item_code)))
		v2_schedule = item.get("custom_so_delivery_schedule")
		if v2_schedule:
			linked = frappe.db.get_value("SO Delivery Schedule", v2_schedule,
				["sales_order", "sales_order_item", "item_code", "warehouse", "delivery_date"], as_dict=True)
			_validate_v2_delivery_schedule_link(item, linked, _delivery_item_schedule_date(item, source))
		from qcmc_logic.api import sales_order_scheduling_service as scheduling
		allocated = frappe.utils.flt(source.delivered_qty) + scheduling._get_draft_delivery_note_qty(source.name)
		if allocated > frappe.utils.flt(source.qty) + 1e-9:
			frappe.throw(_("Sales Order schedule {0} is overallocated. Reconcile its Delivery Notes before proceeding.").format(source.name))
		if item.get("custom_logistics_reason") in ("OR", "ND"):
			sales_date = item.get("custom_sales_move_date")
			if not sales_date or not item.so_detail:
				frappe.throw(_("Sales must complete the date revision for {0} before proceeding.").format(frappe.bold(item.item_code)))
			schedule_date = _delivery_item_schedule_date(item, source)
			if str(schedule_date) != str(sales_date):
				frappe.throw(_("Sales schedule date for {0} does not match its saved DR allocation.").format(frappe.bold(item.item_code)))
		elif item.get("custom_sales_move_date"):
			schedule_date = _delivery_item_schedule_date(item, source)
			if str(schedule_date) != str(item.custom_sales_move_date):
				frappe.throw(_("Sales schedule date for {0} does not match its saved DR allocation.").format(frappe.bold(item.item_code)))

	doc.workflow_state = "For DR Printing"
	doc.save()
	doc.reload()
	if before != _delivery_note_transition_snapshot(doc):
		frappe.throw(_("Delivery Note quantities or commercial values changed during workflow progression. The transition was rolled back."))
	doc.add_comment("Workflow", _("Proceed to DR approved by Sales."))


def _delivery_note_transition_snapshot(doc):
	parent_fields = ("total_qty", "total", "net_total", "base_net_total", "total_taxes_and_charges", "grand_total", "base_grand_total")
	return {
		"items": [(row.name, row.qty, row.stock_qty, row.amount, row.base_amount, row.net_amount,
			row.base_net_amount, row.against_sales_order, row.so_detail, row.get("custom_so_delivery_schedule"),
			row.get("delivery_date")) for row in doc.items],
		"totals": {field: doc.get(field) for field in parent_fields if doc.meta.has_field(field)},
	}


def _validate_saved_logistics_commitment(item):
	reason = item.get("custom_logistics_reason") or ""
	_validate_reason_code(reason)
	if reason in ("SA", "CR", "TO", "SE"):
		proposed_qty = item.get("custom_logistics_proposed_qty")
		if proposed_qty in (None, "") or frappe.utils.flt(proposed_qty) < 0:
			frappe.throw(_("Logistics must save a valid committed quantity for {0} before progression.").format(frappe.bold(item.item_code)))
	if reason in ("OR", "ND") and not item.get("custom_logistics_proposed_date"):
		frappe.throw(_("Logistics must save a proposed date for {0} before progression.").format(frappe.bold(item.item_code)))


def _validate_sales_decision_for_reason(item, decision):
	reason = item.get("custom_logistics_reason") or ""
	if not reason:
		frappe.throw(_("Logistics confirmation is required for item {0}.").format(item.item_code))
	_validate_reason_code(reason)
	if reason == "OK":
		return

	if reason in ("SA", "CR", "TO", "SE"):
		proposed_value = item.get("custom_logistics_proposed_qty")
		if proposed_value in (None, "") or frappe.utils.flt(proposed_value) < 0:
			frappe.throw(_("{0} requires a Logistics Proposed Qty of zero or more for item {1}.").format(reason, frappe.bold(item.item_code)))
		if frappe.utils.flt(proposed_value) == 0:
			if not decision.get("approved_date"):
				frappe.throw(_("Select a Sales Approved Reschedule Date for zero-quantity item {0}.").format(frappe.bold(item.item_code)))
			if not frappe.utils.cint(decision.get("remove_item")):
				frappe.throw(_("Mark zero-quantity item {0} for removal from this DR.").format(frappe.bold(item.item_code)))
		return

	if reason in ("OR", "ND"):
		proposed_date = item.get("custom_logistics_proposed_date")
		if not proposed_date:
			frappe.throw(_("{0} requires a Logistics Proposed Date for item {1}.").format(reason, frappe.bold(item.item_code)))
		approved_date = decision.get("approved_date")
		remove_item = frappe.utils.cint(decision.get("remove_item"))
		approved_qty = frappe.utils.flt(decision.get("approved_qty"))
		if not approved_date:
			frappe.throw(_("Select Move To date for {0}.").format(frappe.bold(item.item_code)))
		if not remove_item and approved_qty > 0:
			frappe.throw(_("{0} must move the whole item {1}; mark Remove or set Final DR Qty to 0.").format(reason, frappe.bold(item.item_code)))


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
	return save_logistics_remarks_bulk([{
		"delivery_note": parent,
		"dn_detail": dn_detail,
		"logistics_reason": "SA",
		"logistics_remarks": remarks,
		"logistics_proposed_qty": new_qty,
		"logistics_proposed_date": None,
	}])


@frappe.whitelist()
def remove_items(dn_details, scheduling_date, reason_code="SA", remarks=None):
	details = list(dict.fromkeys(frappe.parse_json(dn_details)))
	if not details:
		frappe.throw(_("Select at least one Delivery Note item."))
	grouped = {}
	_validate_reason_code(reason_code)
	for detail in details:
		parent = frappe.db.get_value("Delivery Note Item", detail, "parent")
		if not parent:
			frappe.throw(_("Delivery Note Item {0} was not found.").format(detail))
		grouped.setdefault(parent, []).append(detail)

	for parent, selected in grouped.items():
		doc = frappe.get_doc("Delivery Note", parent)
		_validate_delivery_note(doc, require_transact=True)
		marked = [row for row in doc.items if row.name in selected]
		if len(marked) != len(selected):
			frappe.throw(_("One or more selected items no longer belong to {0}.").format(parent))
		for item in marked:
			_set_logistics_recommendation_fields(item, reason_code, remarks, 0, None)
		message = _("Logistics Recommendation: {0} - Proposed removal of item(s): {1}{2}").format(
			reason_code,
			", ".join(frappe.bold(item.item_code) for item in marked),
			_remarks_suffix(remarks),
		)
		doc.save(ignore_permissions=True)
		doc.add_comment("Info", message)
	return _("Saved logistics removal recommendation. Sales approval is required.")


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


def _validate_sales_approval_role():
	roles = set(frappe.get_roles(frappe.session.user))
	if frappe.session.user != "Administrator" and "Sales Coordinator" not in roles:
		frappe.throw(_("You are not allowed to approve Delivery Notes for DR printing."), frappe.PermissionError)


def _validate_sales_review_delivery_note(doc, require_transact=False):
	if doc.docstatus != 0 or doc.workflow_state != "For Stock Confirmation":
		frappe.throw(_("Delivery Note {0} is not available for Sales approval.").format(doc.name))
	for item in doc.items:
		_validate_warehouse_access(item.warehouse, require_transact=require_transact)


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


def _parse_names(values):
	names = list(dict.fromkeys(frappe.parse_json(values or "[]")))
	if not names:
		frappe.throw(_("Select at least one Delivery Note."))
	return names


def _serialize_logistics_item(item, doc=None):
	has_recommendation = bool(
		item.get("custom_logistics_reason")
		or item.get("custom_logistics_remarks")
		or item.get("custom_logistics_proposed_date")
		or frappe.utils.flt(item.get("custom_logistics_proposed_qty"))
	)
	return {
		"delivery_note": doc.name if doc else item.parent,
		"dn_detail": item.name,
		"item_code": item.item_code,
		"item_name": item.item_name,
		"original_qty": item.qty,
		"logistics_proposed_qty": _get_display_logistics_proposed_qty(item) if has_recommendation else None,
		"logistics_proposed_date": item.get("custom_logistics_proposed_date"),
		"logistics_reason": item.get("custom_logistics_reason") or "",
		"logistics_remarks": item.get("custom_logistics_remarks") or "",
	}


def _serialize_review_item(item, doc=None):
	has_recommendation = bool(
		item.get("custom_logistics_reason")
		or item.get("custom_logistics_remarks")
		or item.get("custom_logistics_proposed_date")
		or frappe.utils.flt(item.get("custom_logistics_proposed_qty"))
	)
	proposed_qty = _get_display_logistics_proposed_qty(item) if has_recommendation else None
	remove_item = has_recommendation and proposed_qty is not None and frappe.utils.flt(proposed_qty) == 0
	committed_qty = _get_logistics_committed_qty(item)
	return {
		"delivery_note": doc.name if doc else item.parent,
		"dn_detail": item.name,
		"item_code": item.item_code,
		"item_name": item.item_name,
		"original_qty": item.qty,
		"logistics_committed_qty": committed_qty,
		"logistics_proposed_qty": proposed_qty,
		"logistics_proposed_date": item.get("custom_logistics_proposed_date"),
		"logistics_reason": item.get("custom_logistics_reason") or "",
		"logistics_remarks": item.get("custom_logistics_remarks") or "",
		"available_reschedule_dates": _get_reschedule_date_options_text(item),
		"approved_date_options": _get_reschedule_date_options_select(item),
		"approved_qty": 0 if remove_item else committed_qty,
		"approved_date": item.get("custom_logistics_proposed_date"),
		"remove_item": 1 if remove_item else 0,
	}


def _get_logistics_committed_qty(item):
	has_recommendation = bool(
		item.get("custom_logistics_reason")
		or item.get("custom_logistics_remarks")
		or item.get("custom_logistics_proposed_date")
		or frappe.utils.flt(item.get("custom_logistics_proposed_qty"))
	)
	if has_recommendation and _is_meaningful_proposed_qty(item):
		return frappe.utils.flt(item.get("custom_logistics_proposed_qty"))
	return frappe.utils.flt(item.qty)


def _get_display_logistics_proposed_qty(item):
	return item.get("custom_logistics_proposed_qty") if _is_meaningful_proposed_qty(item) else None


def _is_meaningful_proposed_qty(item):
	proposed_qty = frappe.utils.flt(item.get("custom_logistics_proposed_qty"))
	if proposed_qty:
		return True
	reason = item.get("custom_logistics_reason") or ""
	return bool(reason and reason != "OK" and item.get("custom_logistics_proposed_qty") is not None)


def _clear_logistics_recommendation_fields(item):
	for fieldname in (
		"custom_logistics_reason",
		"custom_logistics_remarks",
		"custom_logistics_proposed_qty",
		"custom_logistics_proposed_date",
	):
		if not getattr(item, "meta", None) or item.meta.has_field(fieldname):
			if callable(getattr(item, "set", None)):
				item.set(fieldname, 0 if fieldname == "custom_logistics_proposed_qty" else None)
			else:
				item[fieldname] = 0 if fieldname == "custom_logistics_proposed_qty" else None


def _get_reschedule_date_options_text(item):
	rows = _get_reschedule_schedule_rows(item)
	return ", ".join("{0} ({1})".format(row.delivery_date, frappe.utils.flt(row.qty)) for row in rows)


def _get_reschedule_date_options_select(item):
	rows = _get_reschedule_schedule_rows(item)
	return "\n".join(str(row.delivery_date) for row in rows)


def _get_reschedule_schedule_rows(item):
	if not item.so_detail or not item.against_sales_order:
		return []
	if item.get("custom_so_delivery_schedule"):
		return frappe.db.sql("""
			SELECT delivery_date, planned_qty AS qty
			FROM `tabSO Delivery Schedule`
			WHERE sales_order_item = %s AND name != %s AND planned_qty > 0
			ORDER BY delivery_date, name
		""", (item.so_detail, item.custom_so_delivery_schedule), as_dict=True)
	return frappe.db.sql(
		"""
		SELECT delivery_date, qty
		FROM `tabSales Order Item`
		WHERE parent = %s
			AND item_code = %s
			AND warehouse = %s
			AND name != %s
		ORDER BY delivery_date, idx, name
		""",
		(item.against_sales_order, item.item_code, item.warehouse, item.so_detail),
		as_dict=True,
	)


def _delivery_item_schedule_date(item, source=None):
	if item.get("custom_so_delivery_schedule"):
		return frappe.db.get_value("SO Delivery Schedule", item.custom_so_delivery_schedule, "delivery_date")
	if source:
		return source.get("custom_next_scheduling_date") or source.delivery_date
	schedule = frappe.db.get_value("Sales Order Item", item.so_detail,
		["delivery_date", "custom_next_scheduling_date"], as_dict=True)
	return (schedule.custom_next_scheduling_date or schedule.delivery_date) if schedule else None


def _validate_v2_delivery_schedule_link(item, linked, operational_date):
	"""Validate v2 identity against the schedule, which owns the operational date.

	ERPNext Delivery Note Item has no persisted delivery_date field. If a future
	custom date field is present, require it to agree as an additional check.
	"""
	dn_item_date = item.get("delivery_date")
	if (
		not linked
		or linked.sales_order != item.against_sales_order
		or linked.sales_order_item != item.so_detail
		or linked.item_code != item.item_code
		or linked.warehouse != item.warehouse
		or not operational_date
		or str(linked.delivery_date) != str(operational_date)
		or (dn_item_date and str(linked.delivery_date) != str(dn_item_date))
	):
		frappe.throw(_("Delivery Note item {0} no longer matches its operational schedule.").format(frappe.bold(item.item_code)))
	return True


def _get_locked_delivery_note(name):
	from qcmc_logic.api.sales_order_schedule_split import lock_orders
	parents = frappe.get_all("Delivery Note Item", filters={"parent": name}, pluck="against_sales_order")
	lock_orders([parent for parent in parents if parent])
	locked_name = frappe.db.sql(
		"SELECT name FROM `tabDelivery Note` WHERE name = %s FOR UPDATE", (name,)
	)
	if not locked_name:
		frappe.throw(_("Delivery Note {0} was not found.").format(name))
	return frappe.get_doc("Delivery Note", name, for_update=True)


@frappe.whitelist()
def get_logistics_reason_options():
	reason_map = _get_logistics_reason_code_map()
	return {
		"options": "\n" + "\n".join(reason_map),
		"meanings": reason_map,
		"default_remarks": _("OK - Good to go"),
		"help_html": "<div class='text-muted small'>{0}</div>".format(
			"<br>".join(
				"{0} - {1}".format(frappe.bold(code), frappe.utils.escape_html(meaning))
				for code, meaning in reason_map.items()
			)
		),
	}


def _get_logistics_reason_code_map():
	if not frappe.db.table_exists("Logistics Reason Code"):
		return DEFAULT_LOGISTICS_REASON_CODES.copy()
	_ensure_default_logistics_reason_codes()
	rows = frappe.get_all(
		"Logistics Reason Code",
		filters={"disabled": 0},
		fields=["code", "meaning"],
		order_by="code asc",
	)
	db_map = {row.code: row.meaning for row in rows}
	ordered = {
		code: db_map[code]
		for code in DEFAULT_LOGISTICS_REASON_CODES
		if code in db_map
	}
	for code, meaning in db_map.items():
		if code not in ordered:
			ordered[code] = meaning
	return ordered or DEFAULT_LOGISTICS_REASON_CODES.copy()


def _ensure_default_logistics_reason_codes():
	for code, meaning in DEFAULT_LOGISTICS_REASON_CODES.items():
		if frappe.db.exists("Logistics Reason Code", code):
			continue
		doc = frappe.new_doc("Logistics Reason Code")
		doc.code = code
		doc.meaning = meaning
		doc.insert(ignore_permissions=True)


def _set_logistics_recommendation_fields(item, reason_code=None, remarks=None, proposed_qty=None, proposed_date=None):
	if frappe.db.has_column("Delivery Note Item", "custom_logistics_reason"):
		item.custom_logistics_reason = reason_code or ""
	if frappe.db.has_column("Delivery Note Item", "custom_logistics_remarks"):
		item.custom_logistics_remarks = remarks or ""
	if frappe.db.has_column("Delivery Note Item", "custom_logistics_proposed_qty"):
		item.custom_logistics_proposed_qty = proposed_qty if proposed_qty is not None else 0
	if frappe.db.has_column("Delivery Note Item", "custom_logistics_proposed_date"):
		item.custom_logistics_proposed_date = proposed_date


def _validate_reason_code(reason_code):
	if reason_code not in _get_logistics_reason_code_map():
		frappe.throw(_("Invalid logistics reason code: {0}").format(reason_code))


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
