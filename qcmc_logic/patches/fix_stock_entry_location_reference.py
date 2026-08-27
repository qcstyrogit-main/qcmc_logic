import frappe


def execute():
	"""Keep every active Location inventory-dimension field on Storage Location."""
	frappe.db.set_value(
		"Custom Field",
		{"dt": "Stock Entry", "fieldname": "location"},
		"options",
		"Storage Location",
		update_modified=False,
	)
	frappe.clear_cache(doctype="Stock Entry")
	frappe.clear_cache(doctype="Stock Entry Detail")
