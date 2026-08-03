import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	create_custom_fields(
		{
			"Work Order Operation": [
				{
					"fieldname": "custom_eps_output_item",
					"label": "EPS Output Item",
					"fieldtype": "Link",
					"options": "Item",
					"insert_after": "operation",
					"in_list_view": 1,
					"read_only": 1,
				},
				{
					"fieldname": "custom_eps_output_type",
					"label": "EPS Output Type",
					"fieldtype": "Select",
					"options": "\nMain Item\nCo-Product\nBy-Product\nScrap\nAdditional Finished Good",
					"insert_after": "custom_eps_output_item",
					"read_only": 1,
				},
				{
					"fieldname": "custom_bom_secondary_item",
					"label": "BOM Secondary Item",
					"fieldtype": "Data",
					"insert_after": "custom_eps_output_type",
					"hidden": 1,
					"read_only": 1,
				},
				{
					"fieldname": "custom_pack_soph",
					"label": "Packing SOPH",
					"fieldtype": "Float",
					"insert_after": "time_in_mins",
					"read_only": 1,
				},
			]
		},
		ignore_validate=True,
	)

	frappe.clear_cache(doctype="Work Order")
	frappe.clear_cache(doctype="Work Order Operation")
