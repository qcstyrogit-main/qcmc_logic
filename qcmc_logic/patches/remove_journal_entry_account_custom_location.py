import frappe


def execute():
	field_name = "Journal Entry Account-custom_location"

	if frappe.db.exists("Custom Field", field_name):
		frappe.delete_doc("Custom Field", field_name, ignore_permissions=True, force=True)

	frappe.clear_cache(doctype="Journal Entry Account")
