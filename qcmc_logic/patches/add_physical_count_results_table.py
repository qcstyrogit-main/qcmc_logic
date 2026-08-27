import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	frappe.reload_doc("qcmc_logics", "doctype", "qcmc_physical_count_result")
	create_custom_fields({
		"Stock Reconciliation": [{
			"fieldname": "custom_physical_count_results_section",
			"label": "Physical Count Results",
			"fieldtype": "Section Break",
			"insert_after": "items",
			"depends_on": "eval:doc.custom_physical_count",
		}, {
			"fieldname": "custom_physical_count_results_summary",
			"label": "Physical Count Results Summary",
			"fieldtype": "HTML",
			"insert_after": "custom_physical_count_results_section",
		}, {
			"fieldname": "custom_physical_count_results",
			"label": "Physical Count Results",
			"fieldtype": "Table",
			"options": "QCMC Physical Count Result",
			"insert_after": "custom_physical_count_results_summary",
			"read_only": 1,
		}]
	}, update=True)
	frappe.clear_cache(doctype="Stock Reconciliation")
