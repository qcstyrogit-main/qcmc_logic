import frappe


def execute():
	for report_name in (
		"Delivery Schedule Confirmation",
		"Delivery Note Printing",
		"Sales Order Delivery Scheduling",
	):
		if frappe.db.exists("Report", report_name):
			frappe.db.set_value("Report", report_name, "disabled", 1, update_modified=False)
	frappe.clear_cache()
