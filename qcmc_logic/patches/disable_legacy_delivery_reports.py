import frappe


def execute():
	for report_name in (
		"Delivery Schedule Confirmation",
		"Delivery Note Printing",
		"Sales Order Delivery Scheduling",
	):
		if frappe.db.exists("Report", report_name):
			report = frappe.get_doc("Report", report_name)
			if not report.disabled:
				report.toggle_disable(True)
	frappe.clear_cache()
