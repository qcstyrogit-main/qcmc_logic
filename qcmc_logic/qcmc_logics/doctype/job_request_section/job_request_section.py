import frappe
from frappe.model.document import Document


class JobRequestSection(Document):
	def validate(self):
		self._validate_no_duplicate_sections()

	def _validate_no_duplicate_sections(self):
		seen = set()
		for row in self.sections or []:
			if not row.section:
				continue
			if row.section in seen:
				frappe.throw(
					f"Duplicate section <b>{row.section}</b> found. Each section may only appear once per Role Profile.",
					title="Duplicate Section",
				)
			seen.add(row.section)
