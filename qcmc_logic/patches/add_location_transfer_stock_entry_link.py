import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	if frappe.get_meta("Location Transfer").has_field("stock_entry"):
		frappe.clear_cache(doctype="Location Transfer")
		return

	create_custom_fields({
		"Location Transfer": [
			{
				"fieldname": "stock_entry",
				"label": "Stock Entry",
				"fieldtype": "Link",
				"options": "Stock Entry",
				"insert_after": "request_id",
				"read_only": 1,
				"no_copy": 1,
			},
		],
	}, update=True)
	frappe.clear_cache(doctype="Location Transfer")
