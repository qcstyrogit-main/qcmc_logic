import frappe


PRINT_FORMAT = "Purchase Receipt Return Slip"
TEMPLATE = "{% include 'qcmc_logic/templates/print_formats/purchase_return_slip.html' %}"


def execute():
	if frappe.db.exists("Print Format", PRINT_FORMAT):
		print_format = frappe.get_doc("Print Format", PRINT_FORMAT)
	else:
		print_format = frappe.new_doc("Print Format")
		print_format.name = PRINT_FORMAT

	print_format.update(
		{
			"doc_type": "Purchase Receipt",
			"module": "Stock",
			"custom_format": 1,
			"print_format_type": "Jinja",
			"html": TEMPLATE,
			"disabled": 0,
			"standard": "No",
			"page_number": "Hide",
			"margin_top": 0,
			"margin_bottom": 0,
			"margin_left": 0,
			"margin_right": 0,
		}
	)
	print_format.save(ignore_permissions=True)
	frappe.clear_cache(doctype="Print Format")
