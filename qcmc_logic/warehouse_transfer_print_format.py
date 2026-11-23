"""Source-controlled Warehouse Transfer Slip print format.

The template under templates/ is the source of truth, not UI edits or fixtures.
Synchronise after migrations to prevent older fixture imports replacing the QR.
"""
from pathlib import Path

import frappe

PRINT_FORMAT = "Warehouse Transfer Slip"
TEMPLATE = Path(__file__).resolve().parent / "templates" / "warehouse_transfer_slip.html"


def ensure_warehouse_transfer_slip():
    """Idempotently synchronize the Jinja print format from application code."""
    html = TEMPLATE.read_text(encoding="utf-8")
    if (
        html.count('class="wts-print"') != 1
        or html.count("get_wts_qr_svg(doc.name)") != 1
        or html.count('class="wts-number"') != 1
    ):
        raise ValueError("Warehouse Transfer Slip template is missing its single-slip/QR structure")

    doc = frappe.get_doc("Print Format", PRINT_FORMAT)
    if doc.doc_type != "Warehouse Transfer":
        raise ValueError("Warehouse Transfer Slip is linked to an unexpected DocType")

    changed = False
    if doc.html != html:
        doc.html = html
        changed = True
    if doc.print_format_type != "Jinja":
        doc.print_format_type = "Jinja"
        changed = True
    if doc.disabled:
        doc.disabled = 0
        changed = True
    if changed:
        doc.save(ignore_permissions=True)
        frappe.clear_cache(doctype="Print Format")
    return {"changed": changed, "format": PRINT_FORMAT}
