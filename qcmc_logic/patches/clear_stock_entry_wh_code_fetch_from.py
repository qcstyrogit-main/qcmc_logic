import frappe


def execute():
	custom_field = "Stock Entry-custom_wh_code"
	if not frappe.db.exists("Custom Field", custom_field):
		return

	frappe.db.set_value(
		"Custom Field",
		custom_field,
		{
			"fetch_from": None,
			"fetch_if_empty": 0,
		},
		update_modified=False,
	)
	frappe.clear_cache(doctype="Stock Entry")
