import frappe
from frappe.model.document import Document


class ScannerWarehouseHandover(Document):
	def validate(self):
		if self.is_new() and not self.created_at:
			self.created_at = frappe.utils.now_datetime()
