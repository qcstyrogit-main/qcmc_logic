import frappe
from frappe import _, _dict
from frappe.utils import flt

from erpnext.manufacturing.doctype.work_order.work_order import create_job_card
from qcmc_logic.api.stock_entry import _get_final_operation
from qcmc_logic.customs.manufacturing_warehouse_access import user_can_transact_work_order


@frappe.whitelist()
def create_next_job_card(work_order):
	"""Create the next shift Job Card for the Work Order's remaining output."""
	if not work_order or not frappe.db.exists("Work Order", work_order):
		frappe.throw(_("Work Order is required and must exist."))

	doc = frappe.get_doc("Work Order", work_order)
	if doc.docstatus != 1:
		frappe.throw(_("Work Order {0} must be submitted.").format(frappe.bold(doc.name)))
	if doc.status in {"Completed", "Closed", "Stopped", "Cancelled"}:
		frappe.throw(
			_("Work Order {0} cannot create another Job Card while its status is {1}.").format(
				frappe.bold(doc.name), frappe.bold(doc.status)
			)
		)
	if not user_can_transact_work_order(doc.name):
		frappe.throw(_("You are not allowed to transact against Work Order {0}.").format(
			frappe.bold(doc.name)
		), frappe.PermissionError)

	remaining_qty = max(flt(doc.qty) - flt(doc.produced_qty), 0)
	if not remaining_qty:
		frappe.throw(_("Work Order {0} has no remaining quantity to manufacture.").format(
			frappe.bold(doc.name)
		))

	operation = _get_final_operation(doc)
	if not operation:
		frappe.throw(_("Work Order {0} has no operation for a Job Card.").format(
			frappe.bold(doc.name)
		))

	# Reuse an unfinished card instead of creating two cards for the same shift.
	existing = frappe.db.get_value(
		"Job Card",
		{
			"work_order": doc.name,
			"operation_id": operation.name,
			"docstatus": 0,
		},
		"name",
		order_by="creation desc",
	)
	if existing:
		return {
			"success": True,
			"job_card": existing,
			"remaining_qty": remaining_qty,
			"created": False,
		}

	operation_values = operation.as_dict() if callable(getattr(operation, "as_dict", None)) else operation
	row = _dict(operation_values)
	row.job_card_qty = remaining_qty
	job_card = create_job_card(doc, row, auto_create=True)

	return {
		"success": True,
		"job_card": job_card.name,
		"remaining_qty": remaining_qty,
		"created": True,
	}
