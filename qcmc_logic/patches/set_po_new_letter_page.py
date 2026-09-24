import frappe

from qcmc_logic.patches.update_po_new_typography import CSS, PRINT_FORMAT


def execute():
    """Match the Letter page size used by the legacy Epson-ready PO PDF."""
    if not frappe.db.exists("Print Format", PRINT_FORMAT):
        return

    frappe.db.set_value("Print Format", PRINT_FORMAT, "css", CSS, update_modified=False)
    frappe.clear_cache(doctype="Print Format")
