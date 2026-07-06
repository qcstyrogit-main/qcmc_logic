import frappe
from frappe import _
from frappe.utils import flt


def validate_final_job_card_time_log(doc, method=None):
	if not _is_linked_manufacture_entry(doc):
		return

	job_card = frappe.get_doc("Job Card", doc.custom_final_job_card)
	if job_card.work_order != doc.work_order:
		frappe.throw(
			_("Final Job Card {0} does not belong to Work Order {1}.").format(
				frappe.bold(job_card.name),
				frappe.bold(doc.work_order),
			)
		)

	time_log_parent = frappe.db.get_value(
		"Job Card Time Log",
		doc.custom_job_card_time_log,
		"parent",
	)
	if time_log_parent != job_card.name:
		frappe.throw(
			_("Actual Time row {0} does not belong to Final Job Card {1}.").format(
				frappe.bold(doc.custom_job_card_time_log),
				frappe.bold(job_card.name),
			)
		)


def update_final_job_card_time_log_on_submit(doc, method=None):
	_update_final_job_card_time_log(doc, multiplier=1)


def update_final_job_card_time_log_on_cancel(doc, method=None):
	_update_final_job_card_time_log(doc, multiplier=-1)


def _is_linked_manufacture_entry(doc):
	return bool(
		doc.purpose == "Manufacture"
		and doc.get("custom_final_job_card")
		and doc.get("custom_job_card_time_log")
	)


def _update_final_job_card_time_log(doc, multiplier):
	if not _is_linked_manufacture_entry(doc):
		return

	completed_qty = flt(doc.fg_completed_qty) * multiplier
	current_qty = flt(
		frappe.db.get_value(
			"Job Card Time Log",
			doc.custom_job_card_time_log,
			"completed_qty",
		)
	)
	updated_qty = current_qty + completed_qty
	if updated_qty < 0:
		frappe.throw(
			_(
				"Cannot reverse {0} from Actual Time row {1}; its current Completed Qty is only {2}."
			).format(
				frappe.bold(abs(completed_qty)),
				frappe.bold(doc.custom_job_card_time_log),
				frappe.bold(current_qty),
			)
		)

	frappe.db.set_value(
		"Job Card Time Log",
		doc.custom_job_card_time_log,
		"completed_qty",
		updated_qty,
		update_modified=False,
	)
	_update_job_card_completed_qty(doc.custom_final_job_card)


def _update_job_card_completed_qty(job_card):
	total_completed_qty = flt(
		frappe.db.get_value(
			"Job Card Time Log",
			{"parent": job_card, "parenttype": "Job Card"},
			"sum(completed_qty)",
		)
	)
	frappe.db.set_value(
		"Job Card",
		job_card,
		"total_completed_qty",
		total_completed_qty,
		update_modified=False,
	)
