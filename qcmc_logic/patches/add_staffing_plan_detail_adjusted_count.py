import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	create_custom_fields(
		{
			"Staffing Plan Detail": [
				{
					"fieldname": "custom_adjusted_count",
					"label": "Adjusted Count",
					"fieldtype": "Int",
					"insert_after": "current_count",
					"default": "0",
					"allow_on_submit": 1,
				},
			]
		},
	)
	frappe.clear_cache(doctype="Staffing Plan Detail")
