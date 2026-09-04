from frappe.model.document import Document

import frappe


class WarehouseWorkflowAudit(Document):
	def before_save(self):
		if not self.is_new():
			frappe.throw("Warehouse Workflow Audit events are immutable.", frappe.PermissionError)

	def on_trash(self):
		frappe.throw("Warehouse Workflow Audit events cannot be deleted.", frappe.PermissionError)
