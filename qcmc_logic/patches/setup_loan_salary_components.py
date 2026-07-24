import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


COMPONENTS = (
	"SSS Loan",
	"SSS Calamity Loan",
	"Pag-Ibig Loan",
	"Pag-IBIG Calamity Loan",
	"Cash Advance",
)
STANDARD_PAYROLL_DEDUCTION_COMPONENTS = {
	"SSS Loan",
	"SSS Calamity Loan",
	"Pag-Ibig Loan",
	"Pag-IBIG Calamity Loan",
}
PRODUCT_COMPONENT_DEFAULTS = {
	"Cash Advance": "Cash Advance",
	"SAL-LOAN": "Cash Advance",
	"SAL-LOAN-QC": "Cash Advance",
}
STANDARD_DEDUCTION_LOAN_PRODUCTS = (
	"SSS Loan",
	"SSS-LOAN",
	"SSS-LOAN-QC",
	"Pag-IBIG Loan",
	"Pag-Ibig Loan",
	"PAGIBIG-LOAN",
	"PAGIBIG-LOAN-QC",
	"SSS-SAL-LOAN-MC",
	"SSS-SAL-LOAN-QC",
	"PAGIBIG-SAL-LOAN-MC",
	"PAGIBIG-SAL-LOAN-QC",
	"PAG-IBIG-CAL-LOAN-MC",
	"PAG-IBIG-CAL-LOAN-QC",
	"SSS-CAL-LOAN-MC",
	"SSS-CAL-LOAN-QC",
)


def execute():
	create_custom_fields(
		{
			"Loan Product": [
				{
					"fieldname": "custom_salary_component",
					"label": "Salary Component",
					"fieldtype": "Link",
					"options": "Salary Component",
					"insert_after": "product_name",
					"description": (
						"Display salary-deducted repayments under this component. "
						"The Loan Repayment remains the accounting source."
					),
				},
			],
			"Salary Detail": [
				{
					"fieldname": "custom_is_loan_repayment_display",
					"label": "Loan Repayment Display Row",
					"fieldtype": "Check",
					"default": "0",
					"hidden": 1,
					"read_only": 1,
					"insert_after": "do_not_include_in_total",
				},
			],
		},
		ignore_validate=True,
	)

	for component_name in COMPONENTS:
		ensure_salary_component(component_name)

	# Convenient defaults for the site's requested product names.
	for product_name, component_name in PRODUCT_COMPONENT_DEFAULTS.items():
		if frappe.db.exists("Loan Product", product_name):
			frappe.db.set_value(
				"Loan Product",
				product_name,
				"custom_salary_component",
				component_name,
				update_modified=False,
			)
	for product_name in STANDARD_DEDUCTION_LOAN_PRODUCTS:
		if frappe.db.exists("Loan Product", product_name):
			frappe.db.set_value(
				"Loan Product",
				product_name,
				"custom_salary_component",
				None,
				update_modified=False,
			)

	sync_active_salary_structures()

	frappe.clear_cache(doctype="Loan Product")
	frappe.clear_cache(doctype="Salary Detail")
	frappe.clear_cache(doctype="Salary Structure")


def ensure_salary_component(component_name):
	if frappe.db.exists("Salary Component", component_name):
		component = frappe.get_doc("Salary Component", component_name)
	else:
		component = frappe.new_doc("Salary Component")
		component.salary_component = component_name

	component.type = "Deduction"
	component.depends_on_payment_days = 0
	is_standard_deduction = component_name in STANDARD_PAYROLL_DEDUCTION_COMPONENTS
	component.do_not_include_in_total = 0 if is_standard_deduction else 1
	component.do_not_include_in_accounts = 0 if is_standard_deduction else 1
	component.remove_if_zero_valued = 1
	component.arrear_component = 0
	component.disabled = 0
	if component_name in {"SSS Loan", "SSS Calamity Loan"}:
		set_component_accounts(
			component,
			{
				"Multiplast Corporation": "2010301 - SSS SALARY LOAN PAYABLE - MC",
				"QC Styropackaging Corporation": "2010301 - SSS SALARY LOAN PAYABLE - QC",
			},
		)
	elif component_name == "Pag-IBIG Calamity Loan":
		set_component_accounts(
			component,
			{
				"Multiplast Corporation": "2010303 - PAG-IBIG LOAN PAYABLE - MC",
				"QC Styropackaging Corporation": "2010303 - PAG-IBIG LOAN PAYABLE - QC",
			},
		)
	component.save(ignore_permissions=True)


def set_component_accounts(component, company_accounts):
	component.set("accounts", [])
	for company, account in company_accounts.items():
		if frappe.db.exists("Account", {"name": account, "company": company, "is_group": 0}):
			component.append("accounts", {"company": company, "account": account})


def sync_active_salary_structures():
	structures = frappe.get_all(
		"Salary Structure",
		filters={"is_active": "Yes", "docstatus": 1},
		pluck="name",
	)

	for structure_name in structures:
		existing_rows = frappe.get_all(
			"Salary Detail",
			filters={
				"parent": structure_name,
				"parenttype": "Salary Structure",
				"parentfield": "deductions",
			},
			fields=["name", "salary_component", "idx"],
		)
		rows_by_component = {row.salary_component: row for row in existing_rows}
		next_idx = max((row.idx or 0 for row in existing_rows), default=0)

		for component_name in COMPONENTS:
			if component_name in rows_by_component:
				is_standard_deduction = component_name in STANDARD_PAYROLL_DEDUCTION_COMPONENTS
				frappe.db.set_value(
					"Salary Detail",
					rows_by_component[component_name].name,
					{
						"do_not_include_in_total": 0 if is_standard_deduction else 1,
						"do_not_include_in_accounts": 0 if is_standard_deduction else 1,
					},
					update_modified=False,
				)
				continue

			next_idx += 1
			row = frappe.new_doc("Salary Detail")
			row.parent = structure_name
			row.parenttype = "Salary Structure"
			row.parentfield = "deductions"
			row.idx = next_idx
			row.salary_component = component_name
			row.amount = 0
			row.default_amount = 0
			is_standard_deduction = component_name in STANDARD_PAYROLL_DEDUCTION_COMPONENTS
			row.do_not_include_in_total = 0 if is_standard_deduction else 1
			row.do_not_include_in_accounts = 0 if is_standard_deduction else 1
			row.db_insert()
