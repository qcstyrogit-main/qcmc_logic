import frappe


PRINT_FORMAT = "QC Salary Slip"


def execute():
	html = frappe.db.get_value("Print Format", PRINT_FORMAT, "html")
	if not html:
		return

	html = html.replace(
		"{% if not d.do_not_include_in_total %}",
		'{% if not d.do_not_include_in_total or d.salary_component == "Cash Advance" %}',
	)
	html = html.replace(
		"frappe.format(doc.total_deduction, {'fieldtype': 'Currency'})",
		"frappe.format(doc.total_deduction + doc.total_loan_repayment, {'fieldtype': 'Currency'})",
	)
	frappe.db.set_value("Print Format", PRINT_FORMAT, "html", html)
