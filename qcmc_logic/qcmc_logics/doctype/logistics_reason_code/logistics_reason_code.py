from frappe.model.document import Document


class LogisticsReasonCode(Document):
	def validate(self):
		if self.code:
			self.code = self.code.strip().upper()

