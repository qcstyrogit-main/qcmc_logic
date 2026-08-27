import frappe


def execute():
	for fieldname in (
		"custom_physical_count_results",
		"custom_physical_count_results_summary",
		"custom_physical_count_results_section",
	):
		name = frappe.db.get_value(
			"Custom Field", {"dt": "Stock Reconciliation", "fieldname": fieldname}
		)
		if name:
			frappe.delete_doc("Custom Field", name, force=True, ignore_permissions=True)
	frappe.clear_cache(doctype="Stock Reconciliation")
