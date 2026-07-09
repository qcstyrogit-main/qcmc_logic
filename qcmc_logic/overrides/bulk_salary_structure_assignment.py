import frappe
from frappe import _
from frappe.utils import get_link_to_form

from hrms.payroll.doctype.bulk_salary_structure_assignment.bulk_salary_structure_assignment import (
	BulkSalaryStructureAssignment,
)
from hrms.payroll.doctype.salary_structure.salary_structure import (
	create_salary_structure_assignment,
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
		self._set_declared_income_default(employees)

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

	def _set_declared_income_default(self, employees):
		for row in employees or []:
			if getattr(row, "custom_declared_income", None) is None:
				row.custom_declared_income = getattr(row, "base", 0) or 0

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

	def _bulk_assign_structure(self, employees: list) -> None:
		success, failure = [], []
		count = 0
		savepoint = "before_salary_assignment"

		for d in employees:
			try:
				frappe.db.savepoint(savepoint)
				assignment = create_salary_structure_assignment(
					employee=d["employee"],
					salary_structure=self.salary_structure,
					company=self.company,
					currency=self.currency,
					payroll_payable_account=self.payroll_payable_account,
					from_date=self.from_date,
					base=d["base"],
					variable=d["variable"],
					income_tax_slab=self.income_tax_slab,
				)
				frappe.db.set_value(
					"Salary Structure Assignment",
					assignment,
					"custom_declared_income",
					self._get_declared_income(d),
					update_modified=False,
				)
			except Exception:
				frappe.db.rollback(save_point=savepoint)
				frappe.log_error(
					f"Bulk Assignment - Salary Structure Assignment failed for employee {d['employee']}.",
					reference_doctype="Salary Structure Assignment",
				)
				failure.append(d["employee"])
			else:
				success.append(
					{
						"doc": get_link_to_form("Salary Structure Assignment", assignment),
						"employee": d["employee"],
					}
				)

			count += 1
			frappe.publish_progress(count * 100 / len(employees), title=_("Assigning Structure..."))

		frappe.publish_realtime(
			"completed_bulk_salary_structure_assignment",
			message={"success": success, "failure": failure},
			doctype="Bulk Salary Structure Assignment",
			after_commit=True,
		)

	def _get_declared_income(self, row):
		if "custom_declared_income" not in row:
			return row.get("base") or 0

		declared_income = row.get("custom_declared_income")
		if declared_income in (None, ""):
			return row.get("base") or 0

		return declared_income

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
