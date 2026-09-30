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

	conditions = ["dn.company = %(company)s", "soi.delivery_date <= %(delivery_date)s"]
	values = {"company": filters.company, "delivery_date": filters.delivery_date}
	if filters.get("warehouse"):
		conditions.append("dni.warehouse = %(warehouse)s")
		values["warehouse"] = filters.warehouse
	_apply_warehouse_scope(conditions, values)
	logistics_reason_sql = "dni.custom_logistics_reason" if frappe.db.has_column("Delivery Note Item", "custom_logistics_reason") else "''"
	logistics_remarks_sql = "dni.custom_logistics_remarks" if frappe.db.has_column("Delivery Note Item", "custom_logistics_remarks") else "''"
	logistics_proposed_qty_sql = "CASE WHEN IFNULL(dni.custom_logistics_reason, '') = '' AND IFNULL(dni.custom_logistics_remarks, '') = '' AND dni.custom_logistics_proposed_date IS NULL THEN NULL ELSE dni.custom_logistics_proposed_qty END" if frappe.db.has_column("Delivery Note Item", "custom_logistics_proposed_qty") else "NULL"
	logistics_proposed_date_sql = "dni.custom_logistics_proposed_date" if frappe.db.has_column("Delivery Note Item", "custom_logistics_proposed_date") else "NULL"

	rows = frappe.db.sql("""
		SELECT dni.name AS dn_detail, dn.name AS delivery_note,
			dni.against_sales_order AS sales_order, dn.customer_name,
			dni.item_code, dni.item_name, dni.warehouse, dni.qty,
			soi.qty AS so_qty, soi.delivered_qty, IFNULL(bin.actual_qty, 0) AS actual_qty,
			soi.delivery_date, {logistics_proposed_qty_sql} AS logistics_proposed_qty,
			{logistics_proposed_date_sql} AS logistics_proposed_date,
			{logistics_reason_sql} AS logistics_reason,
			{logistics_remarks_sql} AS logistics_remarks
		FROM `tabDelivery Note` dn
		JOIN `tabDelivery Note Item` dni ON dni.parent = dn.name
		JOIN `tabSales Order Item` soi ON soi.name = dni.so_detail
		LEFT JOIN `tabBin` bin ON bin.item_code = dni.item_code AND bin.warehouse = dni.warehouse
		WHERE dn.docstatus = 0
			AND dn.workflow_state = 'For Stock Confirmation'
			AND {conditions}
		ORDER BY soi.delivery_date, dn.name, dni.idx
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
	doc = frappe.get_doc("Delivery Note", delivery_note)
	_validate_delivery_note(doc, require_transact=True)
	return [_serialize_logistics_item(row) for row in doc.items]


@frappe.whitelist()
def save_logistics_remarks(delivery_note, items):
	doc = frappe.get_doc("Delivery Note", delivery_note)
	_validate_delivery_note(doc, require_transact=True)
	items = {row.get("dn_detail"): row for row in frappe.parse_json(items or "[]")}
	if not items:
		frappe.throw(_("Enter logistics remarks for at least one item."))
	for item in doc.items:
		values = items.get(item.name)
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
	doc.save(ignore_permissions=True)
	doc.add_comment("Info", _("Logistics Remarks saved. Sales approval is required before DR printing."))
	return _("Saved Logistics Remarks for {0}.").format(doc.name)


@frappe.whitelist()
def get_dr_printing_review_items(delivery_note):
	_validate_sales_approval_role()
	doc = _get_locked_delivery_note(delivery_note)
	_validate_sales_review_delivery_note(doc, require_transact=True)
	return [_serialize_review_item(row) for row in doc.items]


@frappe.whitelist()
def proceed_to_dr_printing(delivery_note, items):
	_validate_sales_approval_role()
	doc = _get_locked_delivery_note(delivery_note)
	_validate_sales_review_delivery_note(doc, require_transact=True)
	decisions = {row.get("dn_detail"): row for row in frappe.parse_json(items or "[]")}
	if not decisions:
		frappe.throw(_("Review at least one Delivery Note item."))

	removed = []
	deferred = []
	for item in list(doc.items):
		decision = decisions.get(item.name)
		if not decision:
			continue
		original_qty = frappe.utils.flt(item.qty)
		approved_qty = frappe.utils.flt(decision.get("approved_qty") if decision.get("approved_qty") is not None else item.qty)
		approved_date = decision.get("approved_date")
		remove_item = frappe.utils.cint(decision.get("remove_item"))
		if remove_item:
			if not approved_date:
				frappe.throw(_("Select a Sales Approved Reschedule Date for removed item {0}.").format(item.item_code))
			removed.append(item)
			deferred.append({
				"item": item,
				"original_qty": original_qty,
				"approved_qty": 0,
				"approved_date": approved_date,
			})
			doc.remove(item)
			continue
		if approved_qty <= 0:
			frappe.throw(_("Approved quantity for {0} must be greater than zero or explicitly marked for removal.").format(item.item_code))
		if approved_qty > original_qty:
			frappe.throw(_("Approved quantity for {0} cannot exceed original DR quantity.").format(item.item_code))
		if approved_qty < original_qty:
			if not approved_date:
				frappe.throw(_("Select a Sales Approved Reschedule Date for the deferred quantity of {0}.").format(item.item_code))
			item.qty = approved_qty
			_set_delivery_note_item_amounts(item)
			deferred.append({
				"item": item,
				"original_qty": original_qty,
				"approved_qty": approved_qty,
				"approved_date": approved_date,
			})
		_clear_logistics_recommendation_fields(item)

	if not doc.items:
		frappe.throw(_("Delivery Note {0} cannot proceed with no items.").format(doc.name))
	doc.run_method("calculate_taxes_and_totals")
	doc.workflow_state = "For DR Printing"
	doc.status = "For DR Printing"
	doc.save(ignore_permissions=True)
	for row in deferred:
		_move_deferred_sales_order_qty(
			row["item"],
			row["approved_qty"],
			row["approved_date"],
			doc.name,
		)
	doc.add_comment("Workflow", _("Proceed to DR approved by Sales."))
	if removed or deferred:
		doc.add_comment("Info", _format_sales_approval_comment(removed, deferred))
	return _("Delivery Note {0} is now For DR Printing.").format(doc.name)


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
	_set_logistics_recommendation_fields(item, "SA", remarks, new_qty, None)
	doc.save(ignore_permissions=True)
	doc.add_comment(
		"Info",
		_("Logistics Recommendation: SA - {0} proposed quantity {1} from original {2}{3}").format(
			frappe.bold(item.item_code), new_qty, old_qty, _remarks_suffix(remarks)
		),
	)
	return _("Saved logistics quantity recommendation for {0}. Sales approval is required.").format(parent)


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


def _serialize_logistics_item(item):
	has_recommendation = bool(
		item.get("custom_logistics_reason")
		or item.get("custom_logistics_remarks")
		or item.get("custom_logistics_proposed_date")
		or frappe.utils.flt(item.get("custom_logistics_proposed_qty"))
	)
	return {
		"dn_detail": item.name,
		"item_code": item.item_code,
		"item_name": item.item_name,
		"original_qty": item.qty,
		"logistics_proposed_qty": item.get("custom_logistics_proposed_qty") if has_recommendation else None,
		"logistics_proposed_date": item.get("custom_logistics_proposed_date"),
		"logistics_reason": item.get("custom_logistics_reason") or "",
		"logistics_remarks": item.get("custom_logistics_remarks") or "",
	}


def _serialize_review_item(item):
	has_recommendation = bool(
		item.get("custom_logistics_reason")
		or item.get("custom_logistics_remarks")
		or item.get("custom_logistics_proposed_date")
		or frappe.utils.flt(item.get("custom_logistics_proposed_qty"))
	)
	proposed_qty = item.get("custom_logistics_proposed_qty") if has_recommendation else None
	remove_item = has_recommendation and proposed_qty is not None and frappe.utils.flt(proposed_qty) == 0
	return {
		"dn_detail": item.name,
		"item_code": item.item_code,
		"item_name": item.item_name,
		"original_qty": item.qty,
		"logistics_proposed_qty": proposed_qty,
		"logistics_proposed_date": item.get("custom_logistics_proposed_date"),
		"logistics_reason": item.get("custom_logistics_reason") or "",
		"logistics_remarks": item.get("custom_logistics_remarks") or "",
		"available_reschedule_dates": _get_reschedule_date_options_text(item),
		"approved_qty": 0 if remove_item else (proposed_qty or item.qty),
		"approved_date": item.get("custom_logistics_proposed_date"),
		"remove_item": 1 if remove_item else 0,
	}


def _set_delivery_note_item_amounts(item):
	item.amount = frappe.utils.flt(item.qty) * frappe.utils.flt(item.rate)
	item.base_amount = frappe.utils.flt(item.qty) * frappe.utils.flt(item.base_rate)
	item.net_amount = frappe.utils.flt(item.qty) * frappe.utils.flt(item.net_rate or item.rate)
	item.base_net_amount = frappe.utils.flt(item.qty) * frappe.utils.flt(item.base_net_rate or item.base_rate)
	item.stock_qty = frappe.utils.flt(item.qty) * frappe.utils.flt(item.conversion_factor or 1)


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
	if not item.so_detail or not item.against_sales_order:
		return ""
	rows = frappe.db.sql(
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
	return ", ".join("{0} ({1})".format(row.delivery_date, frappe.utils.flt(row.qty)) for row in rows)


def _move_deferred_sales_order_qty(item, approved_qty, approved_date, delivery_note):
	if not item.so_detail or not item.against_sales_order:
		return
	target_detail = _get_existing_schedule_detail_for_date(item, approved_date)
	if not target_detail:
		frappe.throw(_(
			"No existing Sales Order schedule was found for {0} on {1}. Select one of the existing reschedule dates for this item."
		).format(frappe.bold(item.item_code), frappe.utils.formatdate(approved_date)))

	from qcmc_logic.qcmc_logics.report.sales_order_delivery_scheduling import (
		sales_order_delivery_scheduling as scheduling,
	)

	details = scheduling._lock_sales_order_items([item.so_detail, target_detail])
	so = frappe.get_doc("Sales Order", item.against_sales_order)
	items = {row.name: row for row in so.items}
	source = items.get(item.so_detail)
	target = items.get(target_detail)
	if not source or not target:
		frappe.throw(_("Selected Sales Order schedules could not be found."))
	if (source.item_code, source.warehouse) != (target.item_code, target.warehouse):
		frappe.throw(_("Deferred quantity can only move to the same item and warehouse."))
	new_source_qty = frappe.utils.flt(approved_qty)
	deferred_qty = frappe.utils.flt(source.qty) - new_source_qty
	if deferred_qty <= 0:
		return
	active_draft_qty = scheduling._get_draft_delivery_note_qty(source.name)
	if frappe.utils.flt(source.delivered_qty) + active_draft_qty > new_source_qty:
		frappe.throw(_("Sales Order schedule {0} still has delivered or active DR quantity above the approved quantity.").format(source.name))

	before_doc = frappe.get_doc("Sales Order", item.against_sales_order)
	scheduling._update_sales_order_schedule_quantities(
		so,
		{
			source.name: new_source_qty,
			target.name: frappe.utils.flt(target.qty) + deferred_qty,
		},
	)
	after_doc = frappe.get_doc("Sales Order", item.against_sales_order)
	version = frappe.new_doc("Version")
	if version.update_version_info(before_doc, after_doc):
		version.insert(ignore_permissions=True)
	after_doc.add_comment(
		"Info",
		_("Sales approval from Delivery Note {0}: deferred {1} qty of {2} to existing schedule date {3}.").format(
			delivery_note,
			deferred_qty,
			frappe.bold(item.item_code),
			frappe.utils.formatdate(approved_date),
		),
	)


def _get_existing_schedule_detail_for_date(item, delivery_date):
	if not delivery_date:
		return None
	return frappe.db.get_value(
		"Sales Order Item",
		{
			"parent": item.against_sales_order,
			"item_code": item.item_code,
			"warehouse": item.warehouse,
			"delivery_date": delivery_date,
			"name": ["!=", item.so_detail],
		},
		"name",
	)


def _format_sales_approval_comment(removed, deferred):
	lines = [_("Sales-approved DR changes:")]
	for item in removed:
		lines.append(_("{0}: removed from DR").format(frappe.bold(item.item_code)))
	for row in deferred:
		item = row["item"]
		lines.append(
			_("{0}: DR quantity {1} to {2}; deferred balance to {3}").format(
				frappe.bold(item.item_code),
				row["original_qty"],
				row["approved_qty"],
				frappe.utils.formatdate(row["approved_date"]),
			)
		)
	return "<br>".join(lines)


def _get_locked_delivery_note(name):
	locked_name = frappe.db.sql(
		"SELECT name FROM `tabDelivery Note` WHERE name = %s FOR UPDATE", (name,)
	)
	if not locked_name:
		frappe.throw(_("Delivery Note {0} was not found.").format(name))
	return frappe.get_doc("Delivery Note", name)


@frappe.whitelist()
def get_logistics_reason_options():
	reason_map = _get_logistics_reason_code_map()
	return {
		"options": "\n" + "\n".join(reason_map),
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
