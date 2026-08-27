import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	create_custom_fields(
		{
			"Pick List": [
				{
					"fieldname": "custom_job_card",
					"label": "Job Card",
					"fieldtype": "Link",
					"options": "Job Card",
					"insert_after": "work_order",
					"read_only": 1,
				},
			],
			"Pick List Item": [
				{
					"fieldname": "custom_job_card_item",
					"label": "Job Card Item",
					"fieldtype": "Link",
					"options": "Job Card Item",
					"insert_after": "material_request_item",
					"read_only": 1,
					"hidden": 1,
				},
			],
		},
		update=True,
	)
