import frappe


PRINT_FORMAT = "Management General Ledger"


def execute():
	template_path = frappe.get_app_path(
		"qcmc_logic",
		"templates",
		"reports",
		"management_general_ledger.html",
	)
	with open(template_path) as template_file:
		html = template_file.read()

	if frappe.db.exists("Print Format", PRINT_FORMAT):
		doc = frappe.get_doc("Print Format", PRINT_FORMAT)
	else:
		doc = frappe.new_doc("Print Format")
		doc.name = PRINT_FORMAT

	doc.update(
		{
			"print_format_for": "Report",
			"report": "General Ledger",
			"module": "QCMC Logics",
			"standard": "No",
			"custom_format": 1,
			"disabled": 0,
			"print_format_type": "JS",
			"html": html,
			"pdf_generator": "wkhtmltopdf",
			"margin_top": 8,
			"margin_bottom": 10,
			"margin_left": 8,
			"margin_right": 8,
			"font_size": 9,
			"page_number": "Bottom Center",
		}
	)
	doc.save(ignore_permissions=True)
