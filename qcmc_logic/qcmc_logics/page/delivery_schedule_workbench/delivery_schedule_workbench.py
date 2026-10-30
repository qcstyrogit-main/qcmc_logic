import frappe
from frappe import _

from qcmc_logic.qcmc_logics.report.delivery_schedule_confirmation import (
	delivery_schedule_confirmation,
)


@frappe.whitelist()
def get_data(filters=None):
	filters = frappe._dict(frappe.parse_json(filters or "{}"))
	columns, rows, message, chart, summary = delivery_schedule_confirmation.execute(filters)
	if not frappe.utils.cint(filters.get("include_overdue")):
		rows = [row for row in rows if str(row.get("delivery_date") or "") == str(filters.get("delivery_date") or "")]
	for row in rows:
		row.workbench_date = filters.get("delivery_date")
		row.document_modified = str(frappe.db.get_value("Delivery Note", row.delivery_note, "modified"))
		_enrich_row(row)
	message = _("{0} item(s) awaiting stock confirmation.").format(len(rows))
	summary = [
		{"value": len({row.delivery_note for row in rows}), "indicator": "Orange", "label": _("Delivery Notes"), "datatype": "Int"},
		{"value": len(rows), "indicator": "Blue", "label": _("Items"), "datatype": "Int"},
	]
	return {
		"columns": columns,
		"rows": rows,
		"message": message,
		"chart": chart,
		"summary": summary,
	}


@frappe.whitelist()
def proceed_to_dr_printing(items):
	"""Release saved DR quantities; old review fields are not quantity instructions."""
	delivery_schedule_confirmation._validate_sales_approval_role()
	rows = frappe.parse_json(items or "[]")
	docs = {}
	for row in rows:
		name = row.get("delivery_note")
		if not name:
			frappe.throw(_("Delivery Note is required."))
		if name not in docs:
			docs[name] = delivery_schedule_confirmation._get_locked_delivery_note(name)
		item = next((item for item in docs[name].items if item.name == row.get("dn_detail")), None)
		if not item:
			frappe.throw(_("Delivery Note changed. Refresh before proceeding."))
		row.update(approved_qty=item.qty, approved_date=None, remove_item=0)
	return delivery_schedule_confirmation.proceed_to_dr_printing_bulk(rows)


@frappe.whitelist()
def get_logistics_reason_options():
	return delivery_schedule_confirmation.get_logistics_reason_options()


@frappe.whitelist()
def preview_whole_dr_move(delivery_note):
	delivery_schedule_confirmation._validate_sales_approval_role()
	doc = frappe.get_doc("Delivery Note", delivery_note)
	delivery_schedule_confirmation._validate_sales_review_delivery_note(doc, require_transact=True)
	doc.check_permission("read")
	return {"name": doc.name, "customer": doc.customer_name, "document_modified": str(doc.modified),
		"items": [{"item_code": item.item_code, "item_name": item.item_name, "qty": item.qty,
			"delivery_date": frappe.db.get_value("Sales Order Item", item.so_detail, "delivery_date")}
			for item in doc.items]}


@frappe.whitelist()
def move_whole_dr(delivery_note, move_date, document_modified):
	from qcmc_logic.qcmc_logics.report.sales_order_delivery_scheduling import sales_order_delivery_scheduling as scheduling
	delivery_schedule_confirmation._validate_sales_approval_role()
	doc = delivery_schedule_confirmation._get_locked_delivery_note(delivery_note)
	delivery_schedule_confirmation._validate_sales_review_delivery_note(doc, require_transact=True)
	doc.check_permission("write")
	if str(doc.modified) != document_modified:
		frappe.throw(_("Delivery Note changed. Reopen the preview before moving it."))
	if not move_date:
		frappe.throw(_("Select a destination date."))
	move_date = frappe.utils.getdate(move_date)
	if not doc.items or any(not item.so_detail or not item.against_sales_order for item in doc.items):
		frappe.throw(_("Every DR item must be linked to a Sales Order schedule."))
	scheduling._lock_sales_order_items([item.so_detail for item in doc.items])
	for item in doc.items:
		so = frappe.get_doc("Sales Order", item.against_sales_order)
		source = next(row for row in so.items if row.name == item.so_detail)
		scheduling._validate_sales_coordinator_access(so, source, require_transact=True)
		if so.docstatus != 1 or so.status in ("Closed", "Completed"):
			frappe.throw(_("Sales Order is no longer available for scheduling."))
		if move_date == frappe.utils.getdate(source.delivery_date):
			continue
		qty = frappe.utils.flt(item.qty)
		remaining = frappe.utils.flt(source.qty) - qty
		other_draft_qty = frappe.utils.flt(frappe.db.sql("""
			SELECT COALESCE(SUM(dni.qty), 0) FROM `tabDelivery Note Item` dni
			JOIN `tabDelivery Note` dn ON dn.name = dni.parent
			WHERE dni.so_detail = %s AND dn.docstatus = 0 AND dn.name != %s
		""", (source.name, doc.name))[0][0])
		if remaining < frappe.utils.flt(source.delivered_qty) + other_draft_qty:
			frappe.throw(_("The schedule no longer has enough quantity to move this DR."))
		# A separate schedule preserves all other DR links and their dates.
		target = frappe.copy_doc(source)
		target.name = None
		target.parent = so.name
		target.parenttype = "Sales Order"
		target.parentfield = "items"
		target.docstatus = so.docstatus
		target.delivery_date = move_date
		target.custom_next_scheduling_date = None
		target.qty = qty
		target.stock_qty = qty * frappe.utils.flt(source.conversion_factor or 1)
		for field in ("delivered_qty", "returned_qty", "billed_amt", "produced_qty", "picked_qty", "ordered_qty", "reserved_qty", "stock_reserved_qty"):
			if target.meta.has_field(field):
				target.set(field, 0)
		scheduling._set_sales_order_item_amounts(target)
		target.idx = len(so.items) + 1
		target.db_insert()
		scheduling._update_sales_order_schedule_quantities(so, {source.name: remaining})
		item.so_detail = target.name
		if item.meta.has_field("delivery_date"):
			item.delivery_date = move_date
		so.add_comment("Info", _("Delivery Note {0}: moved {1} of {2} to {3}.").format(doc.name, qty, frappe.utils.escape_html(item.item_code), move_date))
	for item in doc.items:
		item.custom_logistics_reason = ""
		item.custom_logistics_proposed_qty = 0
		item.custom_logistics_proposed_date = None
		item.custom_sales_final_qty = item.qty
		item.custom_sales_move_date = None
		item.custom_sales_remove = 0
	doc.save()
	doc.add_comment("Info", _("Whole DR moved to {0} by Sales. Logistics must confirm all items again.").format(move_date))
	return {"saved": True}


@frappe.whitelist()
def change_dr_quantity(delivery_note, dn_detail, qty, move_date, document_modified):
	delivery_schedule_confirmation._validate_sales_approval_role()
	doc = delivery_schedule_confirmation._get_locked_delivery_note(delivery_note)
	delivery_schedule_confirmation._validate_sales_review_delivery_note(doc, require_transact=True)
	if str(doc.modified) != document_modified:
		frappe.throw(_("Delivery Note changed. Refresh before editing."))
	item = next((item for item in doc.items if item.name == dn_detail), None)
	if not item:
		frappe.throw(_("Delivery Note item was not found."))
	qty = frappe.utils.flt(qty)
	original_qty = frappe.utils.flt(item.qty)
	if qty < 0 or qty >= original_qty:
		frappe.throw(_("Enter a quantity lower than the current DR quantity, including zero to move the whole item."))
	if not move_date:
		frappe.throw(_("Select the destination date for the balance."))
	if qty > delivery_schedule_confirmation._get_logistics_committed_qty(item):
		frappe.throw(_("Quantity cannot exceed the Logistics commitment."))
	if qty == 0 and len(doc.items) == 1:
		frappe.throw(_("Moving the last item requires moving the whole Delivery Note; this action cannot leave an empty DR."))
	item.qty = qty
	delivery_schedule_confirmation._set_delivery_note_item_amounts(item)
	item.custom_sales_final_qty = qty
	item.custom_sales_move_date = None
	item.custom_sales_remove = 0
	if qty == 0:
		doc.remove(item)
	doc.run_method("calculate_taxes_and_totals")
	doc.save(ignore_permissions=True)
	delivery_schedule_confirmation._move_deferred_sales_order_qty(item, qty, move_date, doc.name, original_qty=original_qty)
	doc.add_comment("Info", _("Changed by Sales: {0}, DR quantity {1} to {2}; balance scheduled on {3}.").format(frappe.utils.escape_html(item.item_code), original_qty, qty, frappe.utils.escape_html(move_date)))
	return {"saved": True}


@frappe.whitelist()
def autosave_item(row):
	row = frappe._dict(frappe.parse_json(row or "{}"))
	if not row.get("delivery_note") or not row.get("dn_detail"):
		frappe.throw(_("Delivery Note and item are required."))

	doc = delivery_schedule_confirmation._get_locked_delivery_note(row.delivery_note)
	if str(doc.modified) != row.get("document_modified"):
		frappe.throw(_("This Delivery Note changed in another session. Reload the workbench before editing."))
	item = next((item for item in doc.items if item.name == row.dn_detail), None)
	if not item:
		frappe.throw(_("Delivery Note Item {0} was not found.").format(row.dn_detail))

	roles = set(frappe.get_roles(frappe.session.user))
	can_logistics = frappe.session.user == "Administrator" or "Stock Confirm User" in roles
	can_sales = frappe.session.user == "Administrator" or "Sales Coordinator" in roles
	if not can_logistics and not can_sales:
		frappe.throw(_("You are not allowed to update this workbench."), frappe.PermissionError)

	if can_logistics:
		delivery_schedule_confirmation._validate_delivery_note(doc, require_transact=True)
		reason_code = row.get("logistics_reason") or ""
		if reason_code:
			delivery_schedule_confirmation._validate_reason_code(reason_code)
		proposed_qty = row.get("logistics_proposed_qty")
		proposed_date = row.get("logistics_proposed_date")
		if reason_code == "OK":
			proposed_qty = None
			proposed_date = None
		elif reason_code in ("SA", "CR", "TO", "SE"):
			proposed_date = None
		elif reason_code in ("OR", "ND"):
			proposed_qty = None
			if reason_code == "ND" and not proposed_date:
				base_date = row.get("workbench_date") or row.get("delivery_date")
				if not base_date:
					frappe.throw(_("Select a delivery date for Next Delivery Date."))
				proposed_date = frappe.utils.add_days(base_date, 1)
		delivery_schedule_confirmation._set_logistics_recommendation_fields(
			item,
			reason_code,
			row.get("logistics_remarks") if "logistics_remarks" in row else item.get("custom_logistics_remarks"),
			proposed_qty,
			proposed_date,
		)

	if can_sales:
		if not can_logistics:
			_validate_sales_logistics_fields_unchanged(item, row)
		delivery_schedule_confirmation._validate_sales_review_delivery_note(doc, require_transact=True)
		_set_sales_decision_fields(item, row)
	if "logistics_remarks" in row:
		item.custom_logistics_remarks = row.logistics_remarks or ""

	doc.save(ignore_permissions=True)
	return {"dn_detail": item.name, "saved": True, "document_modified": str(doc.modified)}


def _enrich_row(row):
	row.logistics_committed_qty = row.logistics_proposed_qty if row.logistics_proposed_qty is not None else row.qty
	row.available_reschedule_dates = ""
	if not row.get("sales_order") or not row.get("item_code") or not row.get("warehouse") or not row.get("dn_detail"):
		return
	fields = ["so_detail"]
	for fieldname in ("custom_sales_final_qty", "custom_sales_move_date", "custom_sales_remove"):
		if frappe.db.has_column("Delivery Note Item", fieldname):
			fields.append(fieldname)
	item_values = frappe.db.get_value("Delivery Note Item", row.dn_detail, fields, as_dict=True)
	if not item_values:
		return
	so_detail = item_values.so_detail
	if frappe.db.has_column("Delivery Note Item", "custom_sales_final_qty"):
		row.sales_final_qty_set = item_values.custom_sales_final_qty not in (None, 0)
		row.approved_qty = item_values.custom_sales_final_qty if item_values.custom_sales_final_qty is not None else row.logistics_committed_qty
	else:
		row.sales_final_qty_set = 0
		row.approved_qty = row.logistics_committed_qty
	if frappe.db.has_column("Delivery Note Item", "custom_sales_move_date"):
		row.approved_date = item_values.custom_sales_move_date
	if frappe.db.has_column("Delivery Note Item", "custom_sales_remove"):
		row.remove_item = item_values.custom_sales_remove
	if (row.logistics_reason in ("OR", "ND")) and not row.sales_final_qty_set and not row.remove_item:
		row.approved_qty = 0
		row.approved_date = row.logistics_proposed_date
		row.remove_item = 1
	if row.logistics_reason in ("SA", "CR", "TO", "SE") and frappe.utils.flt(row.logistics_proposed_qty) == 0 and not row.sales_final_qty_set:
		row.approved_qty = 0
		row.remove_item = 1
	if not so_detail:
		return
	schedules = frappe.db.sql(
		"""
		SELECT delivery_date, qty
		FROM `tabSales Order Item`
		WHERE parent = %s
			AND item_code = %s
			AND warehouse = %s
			AND name != %s
		ORDER BY delivery_date, idx, name
		""",
		(row.sales_order, row.item_code, row.warehouse, so_detail),
		as_dict=True,
	)
	row.available_reschedule_dates = ", ".join(
		"{0} ({1})".format(schedule.delivery_date, frappe.utils.flt(schedule.qty))
		for schedule in schedules
	)


def _set_sales_decision_fields(item, row):
	if frappe.db.has_column("Delivery Note Item", "custom_sales_final_qty"):
		final_qty = row.get("approved_qty")
		item.custom_sales_final_qty = final_qty if final_qty not in (None, "") else 0
	if frappe.db.has_column("Delivery Note Item", "custom_sales_move_date"):
		item.custom_sales_move_date = row.get("approved_date") or None
	if frappe.db.has_column("Delivery Note Item", "custom_sales_remove"):
		item.custom_sales_remove = frappe.utils.cint(row.get("remove_item"))


def _validate_sales_logistics_fields_unchanged(item, row):
	"""Sales may review Logistics fields but cannot overwrite them."""
	if "logistics_reason" in row and (row.get("logistics_reason") or "") != (item.get("custom_logistics_reason") or ""):
		frappe.throw(_("Sales users cannot modify the Logistics Reason for {0}.").format(item.item_code), frappe.PermissionError)
	if "logistics_proposed_qty" in row and frappe.utils.flt(row.get("logistics_proposed_qty")) != frappe.utils.flt(item.get("custom_logistics_proposed_qty")):
		frappe.throw(_("Sales users cannot modify the Logistics Proposed Qty for {0}.").format(item.item_code), frappe.PermissionError)
	if "logistics_proposed_date" in row and str(row.get("logistics_proposed_date") or "") != str(item.get("custom_logistics_proposed_date") or ""):
		frappe.throw(_("Sales users cannot modify the Logistics Proposed Date for {0}.").format(item.item_code), frappe.PermissionError)


