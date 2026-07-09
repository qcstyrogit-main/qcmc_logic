import frappe
from frappe import _
from frappe.utils import flt

from hrms.payroll.doctype.payroll_entry.payroll_entry import PayrollEntry

from qcmc_logic.customs.payroll_role_scope import (
	employee_matches_payroll_role_scope,
	get_payroll_role_rules,
)


class CustomPayrollEntry(PayrollEntry):
	def get_payable_amount_for_earnings_and_deductions(
		self,
		accounts,
		earnings,
		deductions,
		currencies,
		company_currency,
		accounting_dimensions,
		precision,
		payable_amount,
		employee_wise_accounting_enabled,
	):
		self.qcmc_payable_amount_by_cost_center = self.get_payable_amount_by_cost_center(
			earnings, deductions
		)

		return super().get_payable_amount_for_earnings_and_deductions(
			accounts,
			earnings,
			deductions,
			currencies,
			company_currency,
			accounting_dimensions,
			precision,
			payable_amount,
			employee_wise_accounting_enabled,
		)

	def set_payable_amount_against_payroll_payable_account(
		self,
		accounts,
		currencies,
		company_currency,
		accounting_dimensions,
		precision,
		payable_amount,
		payroll_payable_account,
		employee_wise_accounting_enabled,
	):
		if employee_wise_accounting_enabled:
			return super().set_payable_amount_against_payroll_payable_account(
				accounts,
				currencies,
				company_currency,
				accounting_dimensions,
				precision,
				payable_amount,
				payroll_payable_account,
				employee_wise_accounting_enabled,
			)

		payable_by_cost_center = getattr(self, "qcmc_payable_amount_by_cost_center", {})
		if not payable_by_cost_center:
			return super().set_payable_amount_against_payroll_payable_account(
				accounts,
				currencies,
				company_currency,
				accounting_dimensions,
				precision,
				payable_amount,
				payroll_payable_account,
				employee_wise_accounting_enabled,
			)

		for cost_center, amount in payable_by_cost_center.items():
			if not flt(amount, precision):
				continue

			self.get_accounting_entries_and_payable_amount(
				payroll_payable_account,
				cost_center or self.cost_center,
				amount,
				currencies,
				company_currency,
				0,
				accounting_dimensions,
				precision,
				entry_type="payable",
				accounts=accounts,
			)

	def get_payable_amount_by_cost_center(self, earnings, deductions):
		payable_by_cost_center = {}

		for (_account, cost_center), amount in (earnings or {}).items():
			cost_center = cost_center or self.cost_center
			payable_by_cost_center[cost_center] = payable_by_cost_center.get(cost_center, 0) + flt(amount)

		for (_account, cost_center), amount in (deductions or {}).items():
			cost_center = cost_center or self.cost_center
			payable_by_cost_center[cost_center] = payable_by_cost_center.get(cost_center, 0) - flt(amount)

		return payable_by_cost_center

	@frappe.whitelist()
	def fill_employee_details(self):
		result = super().fill_employee_details()
		self.filter_employees_by_payroll_role_scope()

		if not self.employees:
			frappe.throw(
				_("No employees found for your assigned payroll role scope."),
				title=_("No Employees Found"),
			)

		self.number_of_employees = len(self.employees)
		return result

	def before_submit(self):
		self.validate_payroll_role_scope()
		super().before_submit()

	def validate_payroll_role_scope(self):
		rules = self.get_payroll_role_rules()
		if rules is None:
			return

		if not rules:
			frappe.throw(_("You are not allowed to process this payroll frequency."))

		employees = self.get_employee_scope_map([row.employee for row in self.employees if row.employee])
		blocked = [
			row.employee
			for row in self.employees
			if row.employee and not employee_matches_payroll_role_scope(employees.get(row.employee, {}), rules)
		]

		if blocked:
			frappe.throw(
				_("You are not allowed to process payroll for employee(s): {0}").format(
					", ".join(blocked[:10])
				)
			)

	def filter_employees_by_payroll_role_scope(self):
		rules = self.get_payroll_role_rules()
		if rules is None:
			return

		if not rules:
			self.set("employees", [])
			return

		employee_ids = [row.employee for row in self.employees if row.employee]
		employees = self.get_employee_scope_map(employee_ids)

		self.set(
			"employees",
			[
				row
				for row in self.employees
				if employee_matches_payroll_role_scope(employees.get(row.employee, {}), rules)
			],
		)

	def get_payroll_role_rules(self):
		if frappe.session.user == "Administrator":
			return None

		all_rules = get_payroll_role_rules()
		if not all_rules:
			return None

		payroll_type = self.get_employee_payroll_type()
		if payroll_type:
			return [rule for rule in all_rules if rule.get("payroll_type") == payroll_type]

		return all_rules

	def get_employee_payroll_type(self):
		if self.payroll_frequency == "Weekly":
			return "Weekly"

		if self.payroll_frequency in ("Bimonthly", "Monthly"):
			return "Monthly"

		return None

	def get_employee_scope_map(self, employee_ids):
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
