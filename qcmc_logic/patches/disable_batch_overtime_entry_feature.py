import frappe


def execute():
	if frappe.db.exists("Client Script", "Batch Overtime Entry-Form"):
		frappe.db.set_value(
			"Client Script",
			"Batch Overtime Entry-Form",
			"enabled",
			0,
			update_modified=False,
		)
		frappe.clear_cache(doctype="Batch Overtime Entry")

	if frappe.db.exists("Client Script", "Payroll Entry-Batch Overtime"):
		frappe.clear_cache(doctype="Payroll Entry")
