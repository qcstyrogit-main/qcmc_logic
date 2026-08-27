import frappe


def execute():
	name = frappe.db.get_value(
		"Custom Field", {"dt": "Warehouse Transfer Details", "fieldname": "location"}
	)
	if name:
		frappe.db.set_value(
			"Custom Field", name,
			{"label": "Storage Location", "options": "Storage Location", "allow_on_submit": 1},
			update_modified=False,
		)
	frappe.clear_cache(doctype="Warehouse Transfer Details")
