import frappe
from frappe.utils import flt
from frappe.utils.data import getdate


EMPLOYER_COMPONENTS = {
	"SSS Employer Share": "custom_sss_er_share",
	"SSS EC": "custom_sss_ec",
}


def apply_employer_contribution_rows(doc, method=None):
	normalize_sss_contributions(doc)
	normalize_philhealth_contributions(doc)

	for component, fieldname in EMPLOYER_COMPONENTS.items():
		set_employer_component(doc, component, flt(doc.get(fieldname)))

	pagibig_amount = get_pagibig_employer_share(doc)
	set_employer_component(doc, "PAG-IBIG Employer Share", pagibig_amount)


def normalize_philhealth_contributions(doc):
	amount = get_philhealth_amount(doc)
	set_component_amount(doc, "deductions", "PhilHealth/Medic", amount)
	set_employer_component(doc, "PhilHealth Employer Share", amount)


def get_philhealth_amount(doc):
	rule = get_active_philhealth_rule(doc.start_date)
	premium_rate = flt(rule.premium_rate) / 100

	if get_employee_payroll_type(doc) == "Weekly" or doc.payroll_frequency == "Weekly":
		daily_rate = get_employee_daily_rate(doc.employee)
		if not daily_rate:
			return 0
		return flt(
			((daily_rate * flt(rule.monthly_working_days)) * premium_rate)
			/ flt(rule.weekly_divisor),
			2,
		)

	declared_income = get_declared_income(doc)
	if not declared_income:
		return get_component_amount(doc, "deductions", "PhilHealth/Medic")

	monthly_employee_share = (
		flt(rule.minimum_monthly_employee_share)
		if declared_income < flt(rule.minimum_monthly_income)
		else declared_income * premium_rate / 2
	)
	divisor = flt(rule.monthly_cutoff_divisor) if doc.payroll_frequency == "Bimonthly" else 1
	return flt(monthly_employee_share / divisor, 2) if divisor else 0


def get_active_philhealth_rule(posting_date):
	default_rule = frappe._dict(
		premium_rate=5,
		minimum_monthly_income=10000,
		minimum_monthly_employee_share=250,
		monthly_cutoff_divisor=2,
		weekly_divisor=4,
		monthly_working_days=26,
	)

	try:
		if not frappe.db.table_exists("PhilHealth Contribution Rule"):
			return default_rule

		rule = frappe.db.get_value(
			"PhilHealth Contribution Rule",
			{
				"is_active": 1,
				"effectivity_date": ["<=", getdate(posting_date)],
			},
			[
				"premium_rate",
				"minimum_monthly_income",
				"minimum_monthly_employee_share",
				"monthly_cutoff_divisor",
				"weekly_divisor",
				"monthly_working_days",
			],
			order_by="effectivity_date desc",
			as_dict=True,
		)
		return rule or default_rule
	except Exception:
		return default_rule


def normalize_sss_contributions(doc):
	bracket = get_sss_bracket(doc)
	if not bracket:
		set_sss_amounts(doc, 0, 0, 0)
		return

	divisor = get_sss_divisor(doc)
	set_sss_amounts(
		doc,
		flt(bracket.ee_share) / divisor,
		flt(bracket.er_share) / divisor,
		flt(bracket.ec_share) / divisor,
	)


def get_sss_divisor(doc):
	payroll_type = get_employee_payroll_type(doc)
	if payroll_type == "Weekly" or doc.payroll_frequency == "Weekly":
		return 4
	if doc.payroll_frequency == "Bimonthly":
		return 2
	return 1


def get_employee_payroll_type(doc):
	if not doc.employee:
		return ""

	return frappe.db.get_value("Employee", doc.employee, "custom_payroll_type") or ""


def get_employee_daily_rate(employee):
	if not employee:
		return 0

	return flt(frappe.db.get_value("Employee", employee, "custom_mwe_rate_per_day"))


def get_sss_bracket(doc):
	monthly_salary = get_sss_monthly_salary(doc)
	if not monthly_salary:
		return None

	active_tables = frappe.get_all(
		"SSS Table",
		filters={
			"is_active": 1,
			"effectivity_date": ["<=", getdate(doc.start_date)],
		},
		pluck="name",
		order_by="effectivity_date desc",
	)

	for active_table in active_tables:
		bracket = frappe.db.get_value(
			"SSS Table Details",
			{
				"parent": active_table,
				"range_from": ["<=", monthly_salary],
				"range_to": [">=", monthly_salary],
			},
			["ee_share", "er_share", "ec_share"],
			as_dict=True,
		)
		if bracket:
			return bracket

	return None


def get_sss_monthly_salary(doc):
	if get_employee_payroll_type(doc) == "Weekly" or doc.payroll_frequency == "Weekly":
		return get_employee_daily_rate(doc.employee) * 26

	return get_declared_income(doc)


def get_declared_income(doc):
	if not doc.employee or not doc.start_date:
		return 0

	filters = {
		"employee": doc.employee,
		"from_date": ["<=", doc.start_date],
		"docstatus": 1,
	}
	if doc.salary_structure:
		filters["salary_structure"] = doc.salary_structure

	return flt(
		frappe.db.get_value(
			"Salary Structure Assignment",
			filters,
			"custom_declared_income",
			order_by="from_date desc",
		)
	)


def set_sss_amounts(doc, ee_share, er_share, ec_share):
	doc.custom_sss_ee_share = ee_share
	doc.custom_sss_er_share = er_share
	doc.custom_sss_ec = ec_share
	set_component_amount(doc, "deductions", "SSS Premium", ee_share)


def set_component_amount(doc, table_field, component, amount):
	rows = [row for row in doc.get(table_field, []) if row.salary_component == component]
	if not amount:
		doc.set(
			table_field,
			[row for row in doc.get(table_field, []) if row.salary_component != component],
		)
		return

	row = rows[0] if rows else doc.append(table_field, {})
	component_data = frappe.db.get_value(
		"Salary Component",
		component,
		[
			"salary_component_abbr",
			"depends_on_payment_days",
			"do_not_include_in_total",
			"do_not_include_in_accounts",
			"is_tax_applicable",
			"is_flexible_benefit",
			"variable_based_on_taxable_salary",
			"exempted_from_income_tax",
		],
		as_dict=True,
	)
	row.salary_component = component
	row.abbr = component_data.salary_component_abbr if component_data else None
	row.depends_on_payment_days = component_data.depends_on_payment_days if component_data else 0
	row.do_not_include_in_total = component_data.do_not_include_in_total if component_data else 0
	row.do_not_include_in_accounts = component_data.do_not_include_in_accounts if component_data else 0
	row.is_tax_applicable = component_data.is_tax_applicable if component_data else 0
	row.is_flexible_benefit = component_data.is_flexible_benefit if component_data else 0
	row.variable_based_on_taxable_salary = (
		component_data.variable_based_on_taxable_salary if component_data else 0
	)
	row.exempted_from_income_tax = component_data.exempted_from_income_tax if component_data else 0
	row.amount_based_on_formula = 0
	row.formula = ""
	row.default_amount = amount
	row.additional_amount = 0
	row.amount = amount


@frappe.whitelist()
def update_salary_slip_employer_rows(salary_slip):
	doc = frappe.get_doc("Salary Slip", salary_slip)
	apply_employer_contribution_rows(doc)
	doc.save(ignore_permissions=True)
	frappe.db.commit()
	return doc.name


@frappe.whitelist()
def debug_salary_slip_contributions(salary_slip):
	doc = frappe.get_doc("Salary Slip", salary_slip)
	bracket = get_sss_bracket(doc)
	return {
		"employee": doc.employee,
		"payroll_frequency": doc.payroll_frequency,
		"employee_payroll_type": get_employee_payroll_type(doc),
		"daily_rate": get_employee_daily_rate(doc.employee),
		"sss_monthly_salary": get_sss_monthly_salary(doc),
		"sss_bracket": bracket,
		"sss_divisor": get_sss_divisor(doc),
		"philhealth": get_philhealth_amount(doc),
	}


def get_pagibig_employer_share(doc):
	return get_component_amount(doc, "deductions", "PAG-IBIG Premium")


def get_component_amount(doc, table_field, component):
	return sum(flt(row.amount) for row in doc.get(table_field, []) if row.salary_component == component)


def set_employer_component(doc, component, amount):
	rows = [
		row
		for row in doc.get("earnings", [])
		if row.salary_component == component and not row.additional_salary
	]

	if not amount:
		doc.set(
			"earnings",
			[
				row
				for row in doc.get("earnings", [])
				if row.salary_component != component or row.additional_salary
			],
		)
		return

	row = rows[0] if rows else doc.append("earnings", {})
	component_data = frappe.db.get_value(
		"Salary Component",
		component,
		[
			"salary_component_abbr",
			"depends_on_payment_days",
			"do_not_include_in_total",
			"do_not_include_in_accounts",
			"is_tax_applicable",
			"is_flexible_benefit",
			"variable_based_on_taxable_salary",
			"exempted_from_income_tax",
		],
		as_dict=True,
	)

	row.salary_component = component
	row.abbr = component_data.salary_component_abbr if component_data else None
	row.depends_on_payment_days = component_data.depends_on_payment_days if component_data else 0
	row.do_not_include_in_total = 1
	row.do_not_include_in_accounts = 1
	row.is_tax_applicable = component_data.is_tax_applicable if component_data else 0
	row.is_flexible_benefit = component_data.is_flexible_benefit if component_data else 0
	row.variable_based_on_taxable_salary = (
		component_data.variable_based_on_taxable_salary if component_data else 0
	)
	row.exempted_from_income_tax = component_data.exempted_from_income_tax if component_data else 0
	row.default_amount = amount
	row.additional_amount = 0
	row.amount = amount
