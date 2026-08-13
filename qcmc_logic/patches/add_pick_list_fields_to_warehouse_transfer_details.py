import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	if not frappe.db.exists("DocType", "Warehouse Transfer Details"):
		return

	create_custom_fields(
		{
			"Warehouse Transfer Details": [
				{
					"fieldname": "against_pick_list",
					"label": "Against Pick List",
					"fieldtype": "Link",
					"options": "Pick List",
					"insert_after": "reference_doc",
					"read_only": 1,
					"no_copy": 1,
					"print_hide": 1,
				},
				{
					"fieldname": "pick_list_item",
					"label": "Pick List Item",
					"fieldtype": "Data",
					"insert_after": "against_pick_list",
					"read_only": 1,
					"no_copy": 1,
					"print_hide": 1,
				},
			]
		}
	)
	frappe.clear_cache(doctype="Warehouse Transfer Details")
