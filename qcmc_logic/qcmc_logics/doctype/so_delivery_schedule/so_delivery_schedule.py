import frappe
from frappe import _
from frappe.model.document import Document


class SODeliverySchedule(Document):
	def before_insert(self):
		if not frappe.flags.get("delivery_schedule_service_write"):
			frappe.throw(_("Create schedules through the delivery scheduling service."), frappe.PermissionError)
		transfer = frappe.flags.get("delivery_schedule_transfer_context") or {}
		self.original_delivery_date = self.delivery_date
		self.original_qty = 0 if transfer else self.planned_qty
		self.quantity_changes = self.planned_qty if transfer else 0
		self.current_total = self.planned_qty
		self.original_promise_date = transfer.get("promise_date") or self.delivery_date
		self.original_promise_qty = 0 if transfer else self.planned_qty
		self.history_status = "Verified"

	def validate(self):
		from qcmc_logic.api.delivery_schedule_service import validate_schedule_document

		validate_schedule_document(self)

	def after_insert(self):
		if not frappe.flags.get("delivery_schedule_service_write"):
			return
		from qcmc_logic.api.delivery_schedule_service import append_schedule_movement
		if frappe.flags.get("delivery_schedule_transfer_context"):
			return
		append_schedule_movement(operation_type="Initial Commitment", sales_order=self.sales_order,
			sales_order_item=self.sales_order_item, quantity=self.original_qty, uom=self.uom,
			promise_date=self.original_promise_date, promise_qty=self.original_promise_qty,
			promise_commitment=self.name,
			destination_schedule=self.name, destination_before=0, destination_after=self.current_total,
			reason=self.remarks, idempotency_key=f"initial:{self.name}")

	def on_update(self):
		from qcmc_logic.api.delivery_workbench_collaboration import notify_change

		notify_change(self)
