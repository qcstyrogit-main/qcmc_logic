import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	create_custom_fields(
		{
			"BOM Secondary Item": [
				{
					"fieldname": "custom_pack_soph",
					"label": "Packing SOPH",
					"fieldtype": "Float",
					"insert_after": "stock_uom",
					"in_list_view": 1,
					"description": "Packing output per hour for this secondary output item.",
				},
				{
					"fieldname": "custom_packing_workstation",
					"label": "Packing Workstation",
					"fieldtype": "Link",
					"options": "Workstation",
					"insert_after": "custom_pack_soph",
					"in_list_view": 1,
				},
			]
		},
		ignore_validate=True,
	)

	frappe.clear_cache(doctype="BOM")
	frappe.clear_cache(doctype="BOM Secondary Item")
