import json
import frappe
from frappe import _
from frappe.model.document import Document


class AssignChecker(Document):
	def before_validate(self):
		if self.employee and not self.checker_name:
			self.checker_name = frappe.db.get_value("Employee", self.employee, "employee_name")

	def validate(self):
		self.checker_name = str(self.checker_name or "").strip()
		if not self.checker_name:
			frappe.throw(_("Name is required. Select an Employee or enter a name manually."))


@frappe.whitelist()
def get_qr_payload(name):
	checker = frappe.get_doc("Assign Checker", name)
	checker.check_permission("read")
	if checker.disabled:
		frappe.throw(_("Assign Checker {0} is disabled.").format(frappe.bold(checker.name)))

	payload = {
		"name": checker.checker_name,
		"doc_name": checker.name,
	}
	return {
		"payload": json.dumps(payload, separators=(",", ":"), ensure_ascii=False),
		"assign_checker_id": checker.name,
		"name": checker.checker_name,
	}
