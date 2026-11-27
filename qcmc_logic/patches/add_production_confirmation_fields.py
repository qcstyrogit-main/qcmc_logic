from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	create_custom_fields({
		"Job Card Time Log": [
			{
				"fieldname": "qcmc_output_confirmed_at",
				"label": "Output Confirmed At",
				"fieldtype": "Datetime",
				"insert_after": "qcmc_output_entered_at",
				"hidden": 1,
				"read_only": 1,
				"no_copy": 1,
			},
			{
				"fieldname": "qcmc_output_confirmed_by",
				"label": "Output Confirmed By",
				"fieldtype": "Link",
				"options": "User",
				"insert_after": "qcmc_output_confirmed_at",
				"hidden": 1,
				"read_only": 1,
				"no_copy": 1,
			},
		],
		"Stock Entry": [{
			"fieldname": "qcmc_output_allocations",
			"label": "Production Output Allocations",
			"fieldtype": "Long Text",
			"insert_after": "custom_job_card_time_log",
			"hidden": 1,
			"read_only": 1,
			"no_copy": 1,
		}],
	})
