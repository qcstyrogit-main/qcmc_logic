import frappe


def execute():
	for fieldname in (
		"custom_source_storage_location",
		"custom_target_storage_location",
	):
		name = frappe.db.get_value(
			"Custom Field", {"dt": "Warehouse Transfer", "fieldname": fieldname}
		)
		if name:
			frappe.delete_doc("Custom Field", name, force=True, ignore_permissions=True)

	row_location = frappe.db.get_value(
		"Custom Field", {"dt": "Warehouse Transfer Details", "fieldname": "location"}
	)
	if row_location:
		frappe.db.set_value(
			"Custom Field", row_location,
			{"label": "Location", "options": "Location"},
			update_modified=False,
		)

	frappe.clear_cache(doctype="Warehouse Transfer")
	frappe.clear_cache(doctype="Warehouse Transfer Details")
