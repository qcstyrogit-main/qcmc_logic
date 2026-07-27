from collections import defaultdict

import frappe
from frappe.utils import flt


DISPLAY_ROW_FIELD = "custom_is_loan_repayment_display"
LOAN_PRODUCT_COMPONENT_FIELD = "custom_salary_component"


def sync_loan_component_rows(doc, method=None):
	"""Show payroll loan repayments as named deduction rows without deducting twice."""
	if not frappe.get_meta("Salary Detail").has_field(DISPLAY_ROW_FIELD):
		return

	# Regenerate only rows owned by this integration. Normal payroll deductions remain untouched.
	doc.set(
		"deductions",
		[row for row in doc.get("deductions", []) if not row.get(DISPLAY_ROW_FIELD)],
	)

	loan_rows = doc.get("loans", [])
	if not loan_rows or not frappe.get_meta("Loan Product").has_field(LOAN_PRODUCT_COMPONENT_FIELD):
		return

	loan_names = [row.loan for row in loan_rows if row.get("loan")]
	if not loan_names:
		return

	loans = frappe.get_all(
		"Loan",
		filters={"name": ("in", loan_names)},
		fields=["name", "loan_product"],
	)
	product_by_loan = {row.name: row.loan_product for row in loans}
	products = set(product_by_loan.values())
	component_by_product = {
		row.name: row.get(LOAN_PRODUCT_COMPONENT_FIELD)
		for row in frappe.get_all(
			"Loan Product",
			filters={"name": ("in", products)},
			fields=["name", LOAN_PRODUCT_COMPONENT_FIELD],
		)
	}

	amount_by_component = defaultdict(float)
	for row in loan_rows:
		product = product_by_loan.get(row.loan)
		component = component_by_product.get(product)
		if component:
			amount_by_component[component] += flt(row.total_payment)

	for component, amount in amount_by_component.items():
		if not amount:
			continue
		# Existing salary structures in this site contain zero-value placeholders for
		# these components. Reuse one instead of showing a duplicate line.
		display_row = next(
			(
				row
				for row in doc.get("deductions", [])
				if row.salary_component == component and not flt(row.amount)
			),
			None,
		)
		if not display_row:
			display_row = doc.append("deductions", {"salary_component": component})

		display_row.amount = amount
		display_row.do_not_include_in_total = 1
		display_row.do_not_include_in_accounts = 1
		display_row.set(DISPLAY_ROW_FIELD, 1)
