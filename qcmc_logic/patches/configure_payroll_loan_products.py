import frappe


OFFSET_SEQUENCES = {
	"collection_offset_sequence_for_standard_asset": "Standard Collection Offset",
	"collection_offset_sequence_for_sub_standard_asset": "Sub Standard Collection Offset",
	"collection_offset_sequence_for_written_off_asset": "Written Off Collection Offset",
	"collection_offset_sequence_for_settlement_collection": "Settlement Collection Offset",
}

COMPANY_SALARY_LOANS = ("COM-SAL-LOAN-MC", "COM-SAL-LOAN-QC")
STATUTORY_LOAN_PRODUCTS = (
	"SSS-SAL-LOAN-MC",
	"SSS-SAL-LOAN-QC",
	"PAGIBIG-SAL-LOAN-MC",
	"PAGIBIG-SAL-LOAN-QC",
	"PAG-IBIG-CAL-LOAN-MC",
	"PAG-IBIG-CAL-LOAN-QC",
	"SSS-CAL-LOAN-MC",
	"SSS-CAL-LOAN-QC",
)
OFFICIAL_INTEREST_RATES = {
	"SSS-SAL-LOAN-MC": 8,
	"SSS-SAL-LOAN-QC": 8,
	"PAGIBIG-SAL-LOAN-MC": 10.5,
	"PAGIBIG-SAL-LOAN-QC": 10.5,
	"PAG-IBIG-CAL-LOAN-MC": 5.95,
	"PAG-IBIG-CAL-LOAN-QC": 5.95,
	"SSS-CAL-LOAN-MC": 7,
	"SSS-CAL-LOAN-QC": 7,
}


def execute():
	ensure_sss_calamity_products()

	for product_name in frappe.get_all("Loan Product", pluck="name"):
		updates = dict(OFFSET_SEQUENCES)

		if product_name in COMPANY_SALARY_LOANS:
			updates.update(
				{
					"rate_of_interest": 0,
					"penalty_interest_rate": 0,
					"custom_salary_component": "Cash Advance",
				}
			)
		elif product_name in STATUTORY_LOAN_PRODUCTS:
			# Statutory deductions use their real Salary Components and payable
			# accounts; do not add a second Lending display-mirror row.
			updates["custom_salary_component"] = None

		if product_name in OFFICIAL_INTEREST_RATES:
			updates["rate_of_interest"] = OFFICIAL_INTEREST_RATES[product_name]

		frappe.db.set_value(
			"Loan Product",
			product_name,
			updates,
			update_modified=False,
		)

	fix_pagibig_calamity_qc_accounts()
	frappe.clear_cache(doctype="Loan Product")


def ensure_sss_calamity_products():
	products = {
		"SSS-CAL-LOAN-MC": {
			"template": "SSS-SAL-LOAN-MC",
			"product_name": "SSS Calamity Loan - MC",
		},
		"SSS-CAL-LOAN-QC": {
			"template": "SSS-SAL-LOAN-QC",
			"product_name": "SSS Calamity Loan - QC",
		},
	}

	for product_code, settings in products.items():
		if frappe.db.exists("Loan Product", product_code):
			continue

		template_name = settings["template"]
		if not frappe.db.exists("Loan Product", template_name):
			frappe.logger().info(
				"Skipped creating %s because template Loan Product %s does not exist",
				product_code,
				template_name,
			)
			continue

		template = frappe.get_doc("Loan Product", template_name)
		product = frappe.copy_doc(template)
		product.name = None
		product.product_code = product_code
		product.product_name = settings["product_name"]
		product.rate_of_interest = 7
		product.penalty_interest_rate = 0
		product.custom_salary_component = None
		product.insert(ignore_permissions=True)


def fix_pagibig_calamity_qc_accounts():
	product_name = "PAG-IBIG-CAL-LOAN-QC"
	if not frappe.db.exists("Loan Product", product_name):
		return

	frappe.db.set_value(
		"Loan Product",
		product_name,
		{
			"disbursement_account": "1010201 - CASH IN BANK - MBTC - QC",
			"payment_account": "1010201 - CASH IN BANK - MBTC - QC",
			"loan_account": "Calamity Loan Receivable - QC",
			"interest_income_account": "50102 - INTEREST INCOME - QC",
			"penalty_income_account": "LOAN PENALTY INCOME - QC",
		},
		update_modified=False,
	)
