import frappe
from frappe.utils import flt

from qcmc_logic.api.stock_entry import _get_final_operation


def sync_non_final_operation_progress(doc, method=None):
	"""Credit saved Actual Time output from non-final Job Cards to the Work Order."""
	if not doc.work_order or not doc.operation_id or doc.is_corrective_job_card:
		return

	if (
		method == "on_update"
		and getattr(getattr(doc, "flags", None), "in_insert", False)
		and not flt(doc.total_completed_qty)
		and not doc.get("time_logs")
	):
		return

	work_order = frappe.get_doc("Work Order", doc.work_order)
	if work_order.docstatus != 1 or work_order.status == "Stopped":
		return

	final_operation = _get_final_operation(work_order)
	if not final_operation or doc.operation_id == final_operation.name:
		return

	job_cards = frappe.get_all(
		"Job Card",
		filters={
			"operation_id": doc.operation_id,
			"work_order": doc.work_order,
			"docstatus": ("<", 2),
			"is_corrective_job_card": 0,
		},
		fields=["total_completed_qty"],
	)
	completed_qty = sum(flt(row.total_completed_qty) for row in job_cards)

	operation = next(
		(row for row in work_order.operations if row.name == doc.operation_id),
		None,
	)
	if not operation:
		return

	status = _get_operation_status(
		completed_qty,
		flt(work_order.qty),
	)
	frappe.db.set_value(
		"Work Order Operation",
		operation.name,
		{
			"completed_qty": completed_qty,
			# Only physical output may feed the next operation. ERPNext's
			# submission-time shift shortfall must not increase availability.
			"process_loss_qty": 0,
			"status": status,
		},
		update_modified=False,
	)

	if completed_qty and work_order.status == "Not Started":
		frappe.db.set_value(
			"Work Order",
			work_order.name,
			"status",
			"In Process",
			update_modified=False,
		)


def _get_operation_status(accounted_qty, work_order_qty):
	if not accounted_qty:
		return "Pending"
	if accounted_qty < work_order_qty:
		return "Work in Progress"
	return "Completed"
