import frappe


def execute():
	if frappe.db.exists("Custom Field", "User-hide_private"):
		frappe.delete_doc("Custom Field", "User-hide_private", ignore_permissions=True, force=True)
		frappe.clear_cache(doctype="User")
