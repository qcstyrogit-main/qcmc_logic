import frappe
from frappe.utils import flt


TAX_COMPONENT = "Income Tax"


def apply_declared_income_tax(doc, method=None):
	assignment = get_salary_structure_assignment(doc)
	if not assignment:
		remove_income_tax_rows(doc)
		recalculate_salary_slip_totals(doc)
		return

	declared_income = flt(assignment.custom_declared_income)
	tax_amount = get_component_default_tax_amount()
	if not is_declared_income_taxable(declared_income, assignment.income_tax_slab):
		tax_amount = 0

	if tax_amount:
		set_income_tax_amount(doc, tax_amount)
	else:
		remove_income_tax_rows(doc)
	recalculate_salary_slip_totals(doc)


def get_salary_structure_assignment(doc):
	if not doc.employee or not doc.start_date:
		return None

	filters = {
		"employee": doc.employee,
		"from_date": ["<=", doc.start_date],
		"docstatus": 1,
	}
	if doc.salary_structure:
		filters["salary_structure"] = doc.salary_structure

	return frappe.db.get_value(
		"Salary Structure Assignment",
		filters,
		["name", "custom_declared_income", "income_tax_slab"],
		order_by="from_date desc",
		as_dict=True,
	)


def is_declared_income_taxable(declared_income, income_tax_slab):
	if not declared_income or not income_tax_slab:
		return False

	for slab in frappe.get_doc("Income Tax Slab", income_tax_slab).slabs:
		from_amount = flt(slab.from_amount)
		to_amount = flt(slab.to_amount)
		if declared_income < from_amount:
			continue
		if to_amount and declared_income >= to_amount:
			continue
		return flt(slab.percent_deduction) > 0

	return False


def get_component_default_tax_amount():
	component = frappe.db.get_value(
		"Salary Component",
		TAX_COMPONENT,
		["amount", "amount_based_on_formula", "formula"],
		as_dict=True,
	)
	if not component:
		return 0
	if component.amount_based_on_formula:
		try:
			return flt(frappe.safe_eval(str(component.formula or "0"), {"flt": flt}))
		except Exception:
			return 0
	return flt(component.amount)


def set_income_tax_amount(doc, amount):
	rows = [row for row in doc.get("deductions", []) if row.salary_component == TAX_COMPONENT]
	row = rows[0] if rows else doc.append("deductions", {})
	component_data = frappe.db.get_value(
		"Salary Component",
		TAX_COMPONENT,
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

	row.salary_component = TAX_COMPONENT
	row.abbr = component_data.salary_component_abbr if component_data else None
	row.depends_on_payment_days = component_data.depends_on_payment_days if component_data else 0
	row.do_not_include_in_total = component_data.do_not_include_in_total if component_data else 0
	row.do_not_include_in_accounts = component_data.do_not_include_in_accounts if component_data else 0
	row.is_tax_applicable = component_data.is_tax_applicable if component_data else 0
	row.is_flexible_benefit = component_data.is_flexible_benefit if component_data else 0
	row.variable_based_on_taxable_salary = 0
	row.exempted_from_income_tax = component_data.exempted_from_income_tax if component_data else 0
	row.amount_based_on_formula = 0
	row.formula = ""
	row.default_amount = amount
	row.additional_amount = 0
	row.amount = amount


def remove_income_tax_rows(doc):
	doc.set("deductions", [row for row in doc.get("deductions", []) if row.salary_component != TAX_COMPONENT])


def recalculate_salary_slip_totals(doc):
	doc.set_precision_for_component_amounts()
	doc.gross_pay = doc.get_component_totals("earnings", depends_on_payment_days=1)
	doc.base_gross_pay = flt(flt(doc.gross_pay) * flt(doc.exchange_rate))
	doc.total_deduction = doc.get_component_totals("deductions")
	doc.base_total_deduction = flt(flt(doc.total_deduction) * flt(doc.exchange_rate))
	doc.set_net_pay()
	doc.compute_year_to_date()
	doc.compute_month_to_date()
	doc.compute_component_wise_year_to_date()


@frappe.whitelist()
def restore_declared_income_tax_setup(salary_structure=None, salary_slip=None):
	restore_income_tax_component()
	restore_ph_bir_tax_table_2023_monthly_rows()
	if salary_structure:
		restore_salary_structure_income_tax_row(salary_structure)
	if salary_slip:
		doc = frappe.get_doc("Salary Slip", salary_slip)
		doc.save(ignore_permissions=True)
		apply_declared_income_tax(doc)
		doc.save(ignore_permissions=True)
	frappe.clear_cache()
	frappe.db.commit()
	return {"salary_structure": salary_structure, "salary_slip": salary_slip}


def restore_income_tax_component():
	frappe.db.set_value(
		"Salary Component",
		TAX_COMPONENT,
		{
			"amount": 0,
			"amount_based_on_formula": 1,
			"formula": "49.95",
			"variable_based_on_taxable_salary": 0,
			"is_income_tax_component": 1,
		},
	)


def restore_salary_structure_income_tax_row(salary_structure):
	rows = frappe.get_all(
		"Salary Detail",
		filters={
			"parent": salary_structure,
			"parenttype": "Salary Structure",
			"parentfield": "deductions",
			"salary_component": TAX_COMPONENT,
		},
		pluck="name",
	)
	for row_name in rows:
		frappe.db.set_value(
			"Salary Detail",
			row_name,
			{
				"amount": 0,
				"amount_based_on_formula": 1,
				"formula": "49.95",
				"variable_based_on_taxable_salary": 0,
			},
			update_modified=False,
		)


def restore_ph_bir_tax_table_2023_monthly_rows():
	rows = [
		(0, 20833, 0),
		(20833, 33333, 15),
		(33333, 66667, 20),
		(66667, 166667, 25),
		(166667, 666667, 30),
		(666667, 99999999, 35),
	]
	existing_rows = frappe.get_all(
		"Taxable Salary Slab",
		filters={"parent": "PH BIR Tax Table 2023"},
		fields=["name"],
		order_by="idx asc",
	)
	for index, (from_amount, to_amount, percent) in enumerate(rows):
		if index >= len(existing_rows):
			break
		frappe.db.set_value(
			"Taxable Salary Slab",
			existing_rows[index].name,
			{
				"from_amount": from_amount,
				"to_amount": to_amount,
				"percent_deduction": percent,
				"condition": "",
			},
			update_modified=False,
		)
