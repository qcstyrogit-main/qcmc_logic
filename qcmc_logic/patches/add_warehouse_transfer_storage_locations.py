import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	create_custom_fields(
		{
			"Warehouse Transfer": [
				{
					"fieldname": "custom_source_storage_location",
					"label": "Source Storage Location",
					"fieldtype": "Link",
					"options": "Storage Location",
					"insert_after": "source_warehouse",
				},
				{
					"fieldname": "custom_target_storage_location",
					"label": "Target Storage Location",
					"fieldtype": "Link",
					"options": "Storage Location",
					"insert_after": "target_warehouse",
				},
			],
		},
		update=True,
	)
