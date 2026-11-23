"""One-time non-migration update for the existing Warehouse Transfer Slip.

Run:
  bench --site erp.qcstyro.local execute qcmc_logic.patches.add_wts_barcode_to_print_format.execute

Prints an error instead of altering the format if the WTS label and dynamic
WTS number cannot be found together. Existing layout remains untouched apart
from inserting the barcode immediately after its WTS number.
"""
import re
from pathlib import Path
from datetime import datetime

import frappe

NAME = "Warehouse Transfer Slip"
MARKER = "qcmc-wts-barcode-container"


def execute():
    from qcmc_logic.wts_barcode import get_wts_code128_svg

    # Validate the barcode encoder before any database modifications.
    sample = "QC-EDSA-FGWT26-00001"
    rendered = str(get_wts_code128_svg(sample))
    if "qcmc-wts-code128" not in rendered or "rect" not in rendered:
        raise RuntimeError("CODE128 renderer preflight failed")

    doc = frappe.get_doc("Print Format", NAME)
    if doc.doc_type and doc.doc_type != "Warehouse Transfer":
        raise RuntimeError(f"Unexpected Print Format DocType: {doc.doc_type}")
    original = doc.html or ""
    if not original:
        raise RuntimeError("Print Format has no HTML; not changing the layout")
    if MARKER in original:
        print("Warehouse Transfer Slip already contains the barcode; no changes made")
        return {"changed": False, "reason": "already_installed"}

    # Locate a WTS label and ONLY the dynamic document-name expression close
    # to that label. This deliberately avoids replacing an unrelated doc.name.
    labels = list(re.finditer(r"WTS\s*(?:#|No\.?)\s*:?", original, flags=re.I))
    matches = []
    for label in labels:
        window = original[label.end() : label.end() + 700]
        value = re.search(r"\{\{\s*doc\.name\s*\}\}", window)
        if value:
            matches.append((label, label.end() + value.end()))
    if len(matches) != 1:
        contexts = [original[max(0, m.start()-120):m.end()+320] for m in labels[:4]]
        raise RuntimeError(
            f"Expected one dynamic WTS number beside the WTS label; got {len(matches)}. "
            f"Label previews: {contexts!r}. Print Format left unchanged."
        )

    insert_at = matches[0][1]
    snippet = (
        '\n<div class="qcmc-wts-barcode-container" '
        'style="margin:5px 0 0 auto;width:240px;max-width:100%;'
        'line-height:0;page-break-inside:avoid;">'
        '{{ get_wts_code128_svg(doc.name) }}</div>'
    )
    snippet = snippet.replace("qcmc-wts-barcode-container", MARKER)
    updated = original[:insert_at] + snippet + original[insert_at:]

    # Back up the original template on disk before saving the DB change.
    root = Path(__file__).resolve().parents[2]
    backups = root / ".wts_print_format_backups"
    backups.mkdir(exist_ok=True)
    backup = backups / ("Warehouse_Transfer_Slip_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".html")
    backup.write_text(original, encoding="utf-8")

    doc.html = updated
    doc.save(ignore_permissions=True)
    frappe.db.commit()
    frappe.clear_cache()
    print(f"Updated {NAME}; CODE128 under WTS #. Backup: {backup}")
    return {"changed": True, "backup": str(backup), "format": NAME}
