import frappe


def execute():
	frappe.reload_doc("qcmc_logics", "doctype", "physical_count_scan_transaction")
