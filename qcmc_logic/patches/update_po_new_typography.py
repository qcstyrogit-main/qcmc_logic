import frappe


PRINT_FORMAT = "PO_New"

CSS = """
@page { size: Letter; margin: 15mm; }
.print-format { page-size: Letter; margin-top: 15mm; margin-bottom: 15mm; margin-left: 15mm; margin-right: 15mm; }
.headerPO { font-family: Arial, sans-serif !important; font-size: 10pt !important; line-height: 10pt !important; }
.header-content table td, .header-content table th { font-family: Arial, sans-serif !important; font-size: 10pt !important; line-height: 10pt !important; }
.header-content table tr:first-child td:first-child .one-line { font-family: Arial, sans-serif !important; font-size: 11pt !important; font-weight: 700 !important; }
.header-content table tr:first-child td:nth-child(3) .one-line { font-family: Arial, sans-serif !important; font-size: 10pt !important; font-weight: 700 !important; }
.itemsSection, .itemsSection table td, .itemsSection table th { font-family: Verdana, sans-serif !important; font-size: 9pt !important; line-height: 9pt !important; }
.itemsSection table tr:last-child td:last-child { font-family: Verdana, sans-serif !important; font-size: 9pt !important; font-weight: 700 !important; }
.half-footer, .half-footer table td { font-family: Verdana, sans-serif !important; font-size: 10pt !important; line-height: 10pt !important; }
.half-footer table td:last-child { font-family: Verdana, sans-serif !important; font-size: 10pt !important; font-weight: 700 !important; }
""".strip()


def execute():
    """Apply the typography extracted from the legacy Crystal Reports PDF."""
    if not frappe.db.exists("Print Format", PRINT_FORMAT):
        return

    frappe.db.set_value(
        "Print Format",
        PRINT_FORMAT,
        {"font": "Arial", "css": CSS},
        update_modified=False,
    )
    frappe.clear_cache(doctype="Print Format")
