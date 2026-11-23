"""Resize the existing Warehouse Transfer Slip header QR from 96 to 80px.

Run once:
bench --site erp.qcstyro.local execute qcmc_logic.patches.reduce_wts_header_qr.execute

Only changes the QR wrapper dimensions and backs up the original HTML.
"""
from datetime import datetime
from pathlib import Path
import frappe


def execute():
    fmt = frappe.get_doc("Print Format", "Warehouse Transfer Slip")
    original = fmt.html or ""
    marker = 'class="qcmc-wts-header-qr"'
    if original.count(marker) != 1:
        raise RuntimeError("Expected one top-right WTS QR; no changes made")

    start = original.index(marker)
    div_end = original.index("</div>", start)
    section = original[start:div_end]
    if section.count("get_wts_qr_svg(doc.name)") != 1:
        raise RuntimeError("WTS QR expression missing or duplicated; no changes made")
    if "width:80px;height:80px" in section:
        print("Header QR is already 80 x 80 px")
        return {"changed": False}
    if section.count("width:96px;height:96px") != 1:
        raise RuntimeError("Unexpected QR dimensions; no changes made")

    replacement = section.replace("width:96px;height:96px", "width:80px;height:80px", 1)
    updated = original[:start] + replacement + original[div_end:]
    if updated.count("get_wts_qr_svg(doc.name)") != 1:
        raise RuntimeError("QR expression count changed; no changes made")

    backup_dir = Path(__file__).resolve().parents[2] / ".wts_print_format_backups"
    backup_dir.mkdir(exist_ok=True)
    backup = backup_dir / (
        "Warehouse_Transfer_Slip_before_QR_80px_"
        + datetime.now().strftime("%Y%m%d_%H%M%S")
        + ".html"
    )
    backup.write_text(original, encoding="utf-8")
    fmt.html = updated
    fmt.save(ignore_permissions=True)
    frappe.db.commit()
    frappe.clear_cache()
    print(f"Header QR resized to 80 x 80 px. Backup: {backup}")
    return {"changed": True, "backup": str(backup)}
