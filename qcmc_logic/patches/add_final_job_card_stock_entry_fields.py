import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	create_custom_fields(
		{
			"Stock Entry": [
				{
					"fieldname": "custom_final_job_card",
					"label": "Final Job Card",
					"fieldtype": "Link",
					"options": "Job Card",
					"insert_after": "job_card",
					"read_only": 1,
					"in_standard_filter": 1,
					"depends_on": "eval:doc.purpose == 'Manufacture'",
					"description": (
						"Final-operation Job Card used to create this Manufacture Stock Entry."
					),
				},
				{
					"fieldname": "custom_job_card_time_log",
					"label": "Job Card Time Log",
					"fieldtype": "Data",
					"insert_after": "custom_final_job_card",
					"read_only": 1,
					"hidden": 1,
					"description": (
						"Actual Time row whose Completed Qty is synchronized with this entry."
					),
				},
			]
		},
		ignore_validate=True,
	)

	frappe.clear_cache(doctype="Stock Entry")
