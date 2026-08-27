import frappe
from frappe import _
from frappe.utils import bold, flt

from erpnext.manufacturing.doctype.job_card.job_card import JobCard


class CustomJobCard(JobCard):
	def validate_job_card_qty(self):
		"""Validate shift cards against actual output plus still-open commitments.

		A submitted QCMC Job Card is a closed production shift. Its uncompleted
		``for_quantity`` is not process loss and must not reserve Work Order output
		that a later shift needs to manufacture.
		"""
		if not (self.operation_id and self.work_order):
			return

		work_order_qty = flt(frappe.get_cached_value("Work Order", self.work_order, "qty"))
		overproduction = flt(
			frappe.db.get_single_value(
				"Manufacturing Settings", "overproduction_percentage_for_work_order"
			)
		)
		allowed_qty = work_order_qty + (work_order_qty * overproduction / 100)
		completed_qty = flt(
			frappe.db.get_value("Work Order Operation", self.operation_id, "completed_qty")
		)

		# Only unfinished Draft Job Cards reserve future output. Submitted partial
		# shift cards already contribute through operation.completed_qty.
		other_draft_qty = sum(
			max(flt(row.for_quantity) - flt(row.total_completed_qty), 0)
			for row in frappe.get_all(
				"Job Card",
				filters={
					"work_order": self.work_order,
					"operation_id": self.operation_id,
					"docstatus": 0,
					"name": ("!=", self.name),
				},
				fields=["for_quantity", "total_completed_qty"],
			)
		)
		# operation.completed_qty already includes this card's completed scans.
		# Reserve only the portion of the current card that is not completed yet.
		requested_qty = max(
			flt(self.for_quantity) - flt(self.get("total_completed_qty")), 0
		)

		if completed_qty + other_draft_qty + requested_qty > allowed_qty:
			frappe.throw(
				_(
					"Completed quantity ({0}) plus open Job Card quantity ({1}) exceeds "
					"the allowed Work Order quantity ({2}) for operation {3}."
				).format(
					completed_qty,
					other_draft_qty + requested_qty,
					allowed_qty,
					bold(self.operation),
				),
				title=_("Extra Job Card Quantity"),
			)
