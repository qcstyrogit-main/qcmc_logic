import frappe
from frappe import _

from hrms.payroll.doctype.salary_structure_assignment.salary_structure_assignment import (
	SalaryStructureAssignment,
)

from qcmc_logic.customs.payroll_role_scope import (
	employee_matches_payroll_role_scope,
	get_payroll_role_rules,
	get_payroll_type_from_salary_structure,
)


class CustomSalaryStructureAssignment(SalaryStructureAssignment):
	def validate(self):
		self.validate_payroll_role_scope()
		super().validate()

	def validate_payroll_role_scope(self):
		if frappe.session.user == "Administrator":
			return

		all_rules = get_payroll_role_rules()
		if not all_rules:
			return

		payroll_type = get_payroll_type_from_salary_structure(self.salary_structure)
		rules = [
			rule
			for rule in all_rules
			if not payroll_type or rule.get("payroll_type") == payroll_type
		]

		if not rules:
			frappe.throw(_("You are not allowed to assign this Salary Structure."))

		employee = self._get_employee_scope()
		if employee and not employee_matches_payroll_role_scope(employee, rules):
			frappe.throw(
				_("You are not allowed to assign salary structure for employee {0}.").format(
					frappe.bold(self.employee)
				)
			)

	def _get_employee_scope(self):
		if not self.employee:
			return None

		return frappe.db.get_value(
			"Employee",
			self.employee,
			["name", "company", "branch", "employment_type", "custom_payroll_type"],
			as_dict=True,
		)
