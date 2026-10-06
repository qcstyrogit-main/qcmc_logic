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
def get_logistics_reason_options():
	return delivery_schedule_confirmation.get_logistics_reason_options()


@frappe.whitelist()
def autosave_item(row):
	row = frappe._dict(frappe.parse_json(row or "{}"))
	if not row.get("delivery_note") or not row.get("dn_detail"):
		frappe.throw(_("Delivery Note and item are required."))

	doc = frappe.get_doc("Delivery Note", row.delivery_note)
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
			row.get("logistics_remarks"),
			proposed_qty,
			proposed_date,
		)

	if can_sales:
		delivery_schedule_confirmation._validate_sales_review_delivery_note(doc, require_transact=True)
		_set_sales_decision_fields(item, row)

	doc.save(ignore_permissions=True)
	return {"dn_detail": item.name, "saved": True}


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
		row.approved_qty = item_values.custom_sales_final_qty or row.logistics_committed_qty
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
