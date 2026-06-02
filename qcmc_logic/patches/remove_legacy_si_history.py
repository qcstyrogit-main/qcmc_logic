import frappe


def execute():
	if not frappe.db.exists("DocType", "Legacy SI History"):
		return

	if frappe.db.table_exists("Legacy SI History") and frappe.db.count("Legacy SI History"):
		frappe.log_error(
			"Skipped deleting Legacy SI History because it still contains rows.",
			"Remove Legacy SI History",
		)
		return

	frappe.delete_doc("DocType", "Legacy SI History", ignore_permissions=True, force=True)
	frappe.clear_cache(doctype="Legacy SI History")
