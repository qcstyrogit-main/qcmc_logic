import frappe
from frappe import _

from hrms.payroll.doctype.bulk_salary_structure_assignment.bulk_salary_structure_assignment import (
	BulkSalaryStructureAssignment,
)

from qcmc_logic.customs.payroll_role_scope import (
	employee_matches_payroll_role_scope,
	get_payroll_role_rules,
	get_payroll_type_from_salary_structure,
)


class CustomBulkSalaryStructureAssignment(BulkSalaryStructureAssignment):
	@frappe.whitelist()
	def get_employees(self, advanced_filters: list) -> list:
		employees = super().get_employees(advanced_filters)

		rules = self._get_payroll_role_rules()

		# Administrator / no rules configured = allow default HRMS behavior
		if rules is None:
			return employees

		# User has payroll role rules, but none match this salary structure payroll type
		if not rules:
			return []

		employee_ids = [
			getattr(row, "employee", None)
			for row in employees or []
			if getattr(row, "employee", None)
			]

		employee_map = self._get_employee_scope_map(employee_ids)

		return [
			row
			for row in employees or []
			if employee_matches_payroll_role_scope(
				employee_map.get(getattr(row, "employee", None), {}),
				rules,
			)
		]

	@frappe.whitelist()
	def bulk_assign_structure(self, employees: list) -> None:
		rules = self._get_payroll_role_rules()

		# User has payroll role rules, but not allowed for this salary structure
		if rules == []:
			frappe.throw(_("You are not allowed to assign this Salary Structure."))

		if rules:
			employee_ids = self._extract_employee_ids(employees)

			employee_map = self._get_employee_scope_map(employee_ids)

			blocked = [
				employee
				for employee in employee_ids
				if not employee_matches_payroll_role_scope(
					employee_map.get(employee, {}),
					rules,
				)
			]

			if blocked:
				frappe.throw(
					_("You are not allowed to assign salary structure for employee(s): {0}").format(
						", ".join(blocked[:10])
					)
				)

		return super().bulk_assign_structure(employees)

	def _get_payroll_role_rules(self):
		if frappe.session.user == "Administrator":
			return None

		if not self.salary_structure:
			return None

		payroll_type = get_payroll_type_from_salary_structure(self.salary_structure)
		all_rules = get_payroll_role_rules()

		if not all_rules:
			return None

		if payroll_type:
			return [
				rule
				for rule in all_rules
				if rule.get("payroll_type") == payroll_type
			]

		return all_rules

	def _get_employee_scope_map(self, employee_ids):
		if not employee_ids:
			return {}

		rows = frappe.get_all(
			"Employee",
			filters={"name": ["in", list(set(employee_ids))]},
			fields=[
				"name",
				"company",
				"branch",
				"employment_type",
				"custom_payroll_type",
			],
		)

		return {row.name: row for row in rows}

	def _extract_employee_ids(self, employees):
		employee_ids = []

		for row in employees or []:
			if isinstance(row, dict):
				employee = row.get("employee")
			else:
				employee = getattr(row, "employee", None)

			if employee:
				employee_ids.append(employee)

		return employee_ids