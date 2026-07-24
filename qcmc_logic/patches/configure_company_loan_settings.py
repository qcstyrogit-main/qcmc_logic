import frappe


COMPANY_PAYROLL_ACCOUNTS = {
	"QC Styropackaging Corporation": "2120 - Payroll Payable - QC",
	"Multiplast Corporation": "2120 - Payroll Payable - MC",
}

LOAN_SETTINGS = {
	"enable_loan_accounting": 1,
	"enable_async_gl_reversal": 0,
	"interest_day_count_convention": "Actual/365",
	"loan_accrual_frequency": "Daily",
	"min_days_bw_disbursement_first_repayment": 0,
	"loan_restructure_limit": 0,
	"watch_period_post_loan_restructure_in_days": 0,
	"collection_offset_logic_based_on": "NPA Flag",
	"days_past_due_threshold": 90,
	"days_past_due_threshold_for_auto_write_off": 0,
	"collection_offset_sequence_for_standard_asset": "Standard Collection Offset",
	"collection_offset_sequence_for_sub_standard_asset": "Sub Standard Collection Offset",
	"collection_offset_sequence_for_written_off_asset": "Written Off Collection Offset",
	"collection_offset_sequence_for_settlement_collection": "Settlement Collection Offset",
}


def execute():
	for company, payroll_account in COMPANY_PAYROLL_ACCOUNTS.items():
		if not frappe.db.exists("Company", company):
			continue
		if not frappe.db.exists(
			"Account",
			{"name": payroll_account, "company": company, "is_group": 0, "disabled": 0},
		):
			frappe.throw(f"Payroll payable account {payroll_account} is unavailable for {company}")

		# HRMS requires the payroll clearing account to be Payable. Employee-wise
		# payroll accounting supplies the party required by GL validation.
		frappe.db.set_value(
			"Account",
			payroll_account,
			"account_type",
			"Payable",
			update_modified=False,
		)

		frappe.db.set_value(
			"Company",
			company,
			{**LOAN_SETTINGS, "default_payroll_payable_account": payroll_account},
			update_modified=False,
		)

	if frappe.db.exists("DocType", "Loan Origination Settings"):
		frappe.db.set_single_value("Loan Origination Settings", "employee_loans", 1)
	if frappe.db.exists("DocType", "Payroll Settings"):
		frappe.db.set_single_value(
			"Payroll Settings",
			"process_payroll_accounting_entry_based_on_employee",
			1,
		)

	frappe.clear_cache(doctype="Company")
	frappe.clear_cache(doctype="Loan Origination Settings")
