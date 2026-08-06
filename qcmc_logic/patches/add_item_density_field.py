import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	create_custom_fields(
		{
			"Item": [
				{
					"fieldname": "custom_density",
					"label": "Density",
					"fieldtype": "Float",
					"insert_after": "custom_eps_process_main_item",
					"in_standard_filter": 1,
					"description": "Required expanded material density for EPS finished goods.",
				},
			]
		},
		ignore_validate=True,
	)

	frappe.clear_cache(doctype="Item")
