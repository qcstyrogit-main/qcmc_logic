"""Give Process Card QA inspections their own gathering timeframe."""

from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	create_custom_fields({
		"Quality Inspection": [
			{
				"fieldname": "qcmc_work_order",
				"label": "Work Order",
				"fieldtype": "Link",
				"options": "Work Order",
				"read_only": 1,
				"insert_after": "qcmc_process_card",
				"depends_on": "qcmc_process_card",
			},
			{
				"fieldname": "qcmc_qa_start",
				"label": "QA Start Time",
				"fieldtype": "Datetime",
				"insert_after": "qcmc_work_order",
				"depends_on": "qcmc_process_card",
			},
			{
				"fieldname": "qcmc_qa_end",
				"label": "QA End Time",
				"fieldtype": "Datetime",
				"insert_after": "qcmc_qa_start",
				"depends_on": "qcmc_process_card",
			},
			{
				"fieldname": "qcmc_output_time_log",
				"label": "Production Output Interval",
				"fieldtype": "Link",
				"options": "Job Card Time Log",
				"insert_after": "qcmc_process_card",
				"hidden": 1,
			},
		],
	}, update=True)
