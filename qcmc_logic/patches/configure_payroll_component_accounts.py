import frappe


def execute():
	"""Salary Component liabilities are aggregated balances, not Supplier subledgers."""
	component_accounts = frappe.get_all(
		"Salary Component Account",
		filters={"account": ("is", "set")},
		pluck="account",
	)

	for account in set(component_accounts):
		account_details = frappe.db.get_value(
			"Account",
			account,
			["root_type", "account_type", "is_group"],
			as_dict=True,
		)
		if not account_details:
			continue
		if (
			account_details.root_type == "Liability"
			and account_details.account_type == "Payable"
			and not account_details.is_group
		):
			frappe.db.set_value(
				"Account",
				account,
				"account_type",
				"Liability",
				update_modified=False,
			)

	frappe.clear_cache(doctype="Account")
