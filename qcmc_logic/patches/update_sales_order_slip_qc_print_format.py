import frappe


PRINT_FORMAT = "Sales Order Slip QC"
TEMPLATE = "{% include 'qcmc_logic/templates/print_formats/sales_order_slip_qc.html' %}"


def execute():
    if not frappe.db.exists("Print Format", PRINT_FORMAT):
        return

    print_format = frappe.get_doc("Print Format", PRINT_FORMAT)
    print_format.html = TEMPLATE
    print_format.print_format_type = "Jinja"
    print_format.custom_format = 1
    print_format.save(ignore_permissions=True)

    frappe.clear_cache(doctype="Print Format")
    frappe.clear_cache(doctype="Sales Order")
