import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	remove_item_density_field()
	create_custom_fields(
		{
			"BOM": [
				{
					"fieldname": "custom_density",
					"label": "Density",
					"fieldtype": "Float",
					"insert_after": "custom_machine",
					"in_standard_filter": 1,
					"description": "Required expanded material density for this BOM.",
				},
			]
		},
		ignore_validate=True,
	)

	frappe.clear_cache(doctype="Item")
	frappe.clear_cache(doctype="BOM")


def remove_item_density_field():
	custom_field = "Item-custom_density"
	if frappe.db.exists("Custom Field", custom_field):
		frappe.delete_doc("Custom Field", custom_field, ignore_permissions=True, force=True)
