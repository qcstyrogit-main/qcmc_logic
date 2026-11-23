import frappe
from frappe.utils import flt

from qcmc_logic.api.stock_entry import _get_final_operation


def sync_non_final_operation_progress(doc, method=None):
	"""Credit actual shift output without treating unfinished quantity as loss."""
	# Workbench checkpoints are operational-only metadata on native Time Log rows.
	# Their completed_qty is zero; do not run the official progressive Work Order sync.
	if getattr(getattr(doc, "flags", None), "qcmc_operational_checkpoint_update", False):
		return
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
	if not final_operation:
		return

	# A QCMC Job Card represents one shift. Completing less than for_quantity
	# leaves production for a later Job Card; it is not manufacturing process
	# loss. True process loss must be recorded through its dedicated flow.
	if flt(doc.get("process_loss_qty")):
		frappe.db.set_value(
			"Job Card", doc.name, "process_loss_qty", 0, update_modified=False
		)

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


def repair_shift_process_loss(job_card_name):
	"""Repair shift shortfall previously stored as manufacturing process loss."""
	doc = frappe.get_doc("Job Card", job_card_name)
	sync_non_final_operation_progress(doc, "repair")
	doc.reload()
	operation = frappe.get_doc("Work Order Operation", doc.operation_id)
	return {
		"job_card": doc.name,
		"for_quantity": flt(doc.for_quantity),
		"completed_quantity": flt(doc.total_completed_qty),
		"job_card_process_loss": flt(doc.process_loss_qty),
		"operation_completed_quantity": flt(operation.completed_qty),
		"operation_process_loss": flt(operation.process_loss_qty),
		"operation_status": operation.status,
	}


_OPERATIONAL_OUTPUT_FIELDS = (
	"qcmc_process_card",
	"qcmc_good_qty",
	"qcmc_rejected_qty",
	"qcmc_output_remarks",
	"qcmc_output_entered_at",
	"qcmc_output_entered_by",
	"qcmc_output_revision",
	"qcmc_output_correction_history",
)


def _operational_output_state(row):
	output_state = tuple(row.get(field) for field in _OPERATIONAL_OUTPUT_FIELDS)
	meaningful = (
		int(row.get("qcmc_output_revision") or 0) > 0
		or any(value not in (None, "", 0, 0.0, "0", "[]") for value in output_state[1:])
	)
	state = output_state + (
		row.get("from_time"),
		row.get("to_time"),
		row.get("completed_qty"),
		row.get("employee"),
	)
	return state, meaningful


def prevent_untracked_output_checkpoint_changes(doc, method=None):
	"""Keep hidden native child fields writable only through the audited Workbench APIs."""
	if getattr(getattr(doc, "flags", None), "qcmc_operational_checkpoint_update", False):
		return
	previous = doc.get_doc_before_save()
	previous_rows = {}
	if previous:
		for row in previous.get("time_logs") or []:
			state, meaningful = _operational_output_state(row)
			if row.name and meaningful:
				previous_rows[row.name] = state
	current_rows = {}
	for row in doc.get("time_logs") or []:
		state, meaningful = _operational_output_state(row)
		if not meaningful:
			continue
		if not row.name or row.name not in previous_rows or previous_rows[row.name] != state:
			frappe.throw("Operational checkpoint data can only be changed through the Process Card Workbench.")
		current_rows[row.name] = state
	if any(name not in current_rows for name in previous_rows):
		frappe.throw("Operational checkpoint rows cannot be removed. Use the audited correction action.")
