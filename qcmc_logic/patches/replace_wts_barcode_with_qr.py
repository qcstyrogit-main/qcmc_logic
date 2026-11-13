"""Replace only the Warehouse Transfer Slip scanner barcode with a QR code.

Run:
  bench --site erp.qcstyro.local execute qcmc_logic.patches.replace_wts_barcode_with_qr.execute

Preserves WTS # text, item rows and all other slip content. Backups the
original live Print Format HTML; safe to run twice.
"""
from datetime import datetime
from pathlib import Path
import re

import frappe


def execute():
    from qcmc_logic.wts_qr import get_wts_qr_svg

    sample = "QC-SC-FGWT26-00001"
    svg = str(get_wts_qr_svg(sample))
    if 'class="qcmc-wts-qr"' not in svg or "<rect" not in svg:
        raise RuntimeError("QR renderer preflight failed; no changes made")

    fmt = frappe.get_doc("Print Format", "Warehouse Transfer Slip")
    original = fmt.html or ""
    if fmt.doc_type and fmt.doc_type != "Warehouse Transfer":
        raise RuntimeError("Unexpected Print Format document type; no changes made")
    if original.count("get_wts_qr_svg(doc.name)") == 1 and "get_wts_code128_svg(doc.name)" not in original:
        print("WTS QR already installed; no changes made")
        return {"changed": False, "reason": "already_installed"}

    marker = 'class="qcmc-wts-scanner-row"'
    if original.count(marker) != 1:
        raise RuntimeError("Expected one existing WTS barcode row; no changes made")
    start = original.index(marker)
    row_start = original.rfind("<tr", 0, start)
    end = original.find("</tr>", start)
    if row_start < 0 or end < 0:
        raise RuntimeError("Cannot isolate existing barcode row; no changes made")
    end += len("</tr>")
    existing = original[row_start:end]
    if existing.count("get_wts_code128_svg(doc.name)") != 1:
        raise RuntimeError("Existing CODE128 renderer not found; no changes made")

    replacement = (
        '<tr class="qcmc-wts-scanner-row">'
        '<td colspan="3" style="padding:2px 0 5px;text-align:right;white-space:normal;">'
        '<div style="display:inline-block;width:120px;height:120px;'
        'max-width:100%;line-height:0;background:#fff;">'
        '{{ get_wts_qr_svg(doc.name) }}'
        '</div></td></tr>'
    )
    updated = original[:row_start] + replacement + original[end:]
    if updated.count("get_wts_qr_svg(doc.name)") != 1 or "get_wts_code128_svg(doc.name)" in updated:
        raise RuntimeError("QR replacement validation failed; no changes made")

    backup_dir = Path(__file__).resolve().parents[2] / ".wts_print_format_backups"
    backup_dir.mkdir(exist_ok=True)
    backup_path = backup_dir / (
        "Warehouse_Transfer_Slip_before_QR_"
        + datetime.now().strftime("%Y%m%d_%H%M%S")
        + ".html"
    )
    backup_path.write_text(original, encoding="utf-8")

    fmt.html = updated
    fmt.save(ignore_permissions=True)
    frappe.db.commit()
    frappe.clear_cache()
    print(f"Replaced WTS CODE128 with 120px QR. Backup: {backup_path}")
    return {"changed": True, "backup": str(backup_path), "format": fmt.name}
