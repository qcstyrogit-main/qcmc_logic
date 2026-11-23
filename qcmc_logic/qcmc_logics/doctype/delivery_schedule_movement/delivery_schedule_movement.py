import frappe
from frappe import _
from frappe.model.document import Document


class DeliveryScheduleMovement(Document):
	def validate(self):
		if not frappe.flags.get("delivery_schedule_movement_service_write"):
			frappe.throw(_("Schedule movements can only be created by the scheduling service."), frappe.PermissionError)
		if not self.is_new():
			frappe.throw(_("Schedule movement history is append-only."), frappe.PermissionError)

	def on_trash(self):
		frappe.throw(_("Schedule movement history cannot be deleted."), frappe.PermissionError)
