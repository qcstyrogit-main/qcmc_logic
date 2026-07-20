import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	create_custom_fields(
		{
			"Item": [
				{
					"fieldname": "custom_is_eps_process_main_item",
					"label": "Is EPS Process Main Item",
					"fieldtype": "Check",
					"insert_after": "default_bom",
					"description": (
						"Marks this Item as the grouping item for EPS items produced together."
					),
				},
				{
					"fieldname": "custom_eps_process_main_item",
					"label": "EPS Process Main Item",
					"fieldtype": "Link",
					"options": "Item",
					"insert_after": "custom_is_eps_process_main_item",
					"in_standard_filter": 1,
					"link_filters": (
						'[[\"Item\", \"custom_is_eps_process_main_item\", \"=\", 1], '
						'[\"Item\", \"disabled\", \"=\", 0]]'
					),
					"description": (
						"Select the EPS process grouping Item this output is produced with."
					),
				},
			]
		},
		ignore_validate=True,
	)

	frappe.clear_cache(doctype="Item")
