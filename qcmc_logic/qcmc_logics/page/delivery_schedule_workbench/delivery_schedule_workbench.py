import frappe
from frappe import _
from qcmc_logic.api import delivery_workbench_collaboration as collaboration

from qcmc_logic.api import delivery_confirmation_service as confirmation


@frappe.whitelist()
def get_data(filters=None):
	frappe.throw(_("Old Delivery Note workbench is retired. Open Delivery Schedule Workbench."))
	collaboration._role_check()
	revision = collaboration.revision()
	filters = frappe._dict(frappe.parse_json(filters or "{}"))
	columns, rows, message, chart, summary = confirmation.execute(filters)
	if not frappe.utils.cint(filters.get("include_overdue")):
		rows = [row for row in rows if str(row.get("delivery_date") or "") == str(filters.get("delivery_date") or "")]
	readable = {}
	for name in {row.delivery_note for row in rows}:
		readable[name] = frappe.has_permission("Delivery Note", "read", doc=frappe.get_doc("Delivery Note", name))
	rows = [row for row in rows if readable[row.delivery_note]]
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
		"revision": revision,
	}


@frappe.whitelist()
def proceed_to_dr_printing(items):
	frappe.throw(_("Release schedules through Delivery Schedule Workbench."))
	"""Release saved DR quantities; old review fields are not quantity instructions."""
	confirmation._validate_sales_approval_role()
	rows = frappe.parse_json(items or "[]")
	docs = {}
	for row in rows:
		name = row.get("delivery_note")
		if not name:
			frappe.throw(_("Delivery Note is required."))
		if name not in docs:
			docs[name] = confirmation._get_locked_delivery_note(name)
			collaboration.bind_edit(docs[name], row.get("edit_token"))
		item = next((item for item in docs[name].items if item.name == row.get("dn_detail")), None)
		if not item:
			frappe.throw(_("Delivery Note changed. Refresh before proceeding."))
		row.update(approved_qty=item.qty, approved_date=None, remove_item=0)
	return confirmation.proceed_to_dr_printing_bulk(rows)


@frappe.whitelist()
def get_logistics_reason_options():
	return confirmation.get_logistics_reason_options()


@frappe.whitelist()
def preview_whole_dr_move(delivery_note):
	from qcmc_logic.api.delivery_schedule_revision import _validate_v2_sales_edit_draft
	confirmation._validate_sales_approval_role()
	doc = frappe.get_doc("Delivery Note", delivery_note)
	_validate_v2_sales_edit_draft(doc)
	return {"name": doc.name, "customer": doc.customer_name, "document_modified": str(doc.modified),
		"items": [{"item_code": item.item_code, "item_name": item.item_name, "qty": item.qty,
			"delivery_date": frappe.db.get_value("SO Delivery Schedule", item.custom_so_delivery_schedule, "delivery_date")}
			for item in doc.items]}

@frappe.whitelist()
def move_whole_dr(delivery_note, move_date, document_modified, edit_token=None, remarks=None):
	from qcmc_logic.api.delivery_schedule_revision import move_delivery_note_date
	return move_delivery_note_date(delivery_note, move_date, document_modified, edit_token=edit_token, remarks=remarks)


@frappe.whitelist()
def change_dr_quantity(delivery_note, dn_detail, qty, move_date, document_modified, edit_token=None, remarks=None):
	from qcmc_logic.api.delivery_schedule_revision import revise_delivery_note_item
	return revise_delivery_note_item(
		delivery_note, dn_detail, qty, move_date, document_modified, edit_token=edit_token, remarks=remarks
	)


@frappe.whitelist()
def autosave_item(row):
	frappe.throw(_("Sales and Logistics decisions are recorded on SO Delivery Schedule."))
	row = frappe._dict(frappe.parse_json(row or "{}"))
	if not row.get("delivery_note") or not row.get("dn_detail"):
		frappe.throw(_("Delivery Note and item are required."))

	doc = confirmation._get_locked_delivery_note(row.delivery_note)
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
	collaboration.bind_edit(doc, row.get("edit_token"))

	if can_logistics:
		confirmation._validate_delivery_note(doc, require_transact=True)
		reason_code = row.get("logistics_reason") or ""
		if reason_code:
			confirmation._validate_reason_code(reason_code)
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
		confirmation._set_logistics_recommendation_fields(
			item,
			reason_code,
			row.get("logistics_remarks") if "logistics_remarks" in row else item.get("custom_logistics_remarks"),
			proposed_qty,
			proposed_date,
		)

	if can_sales:
		if not can_logistics:
			_validate_sales_logistics_fields_unchanged(item, row)
		confirmation._validate_sales_review_delivery_note(doc, require_transact=True)
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


