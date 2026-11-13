"""Resize Warehouse Transfer Slip top-right QR from 80px to 64px.

Run once:
bench --site erp.qcstyro.local execute qcmc_logic.patches.reduce_wts_header_qr_64.execute

Only modifies the inline QR wrapper dimensions, preserving the full SVG
quiet zone and all transaction information. Saves an HTML backup.
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
    div_end = original.find("</div>", start)
    if div_end < 0:
        raise RuntimeError("Cannot find QR container closing tag")
    section = original[start:div_end]
    if section.count("get_wts_qr_svg(doc.name)") != 1:
        raise RuntimeError("WTS QR expression missing or duplicated")

    if section.count("width:64px;height:64px") == 1:
        print("WTS header QR is already 64 x 64 px")
        return {"changed": False}
    if section.count("width:80px;height:80px") != 1:
        raise RuntimeError("Expected existing 80px QR container; no changes made")

    resized = section.replace("width:80px;height:80px", "width:64px;height:64px", 1)
    updated = original[:start] + resized + original[div_end:]
    if updated.count("get_wts_qr_svg(doc.name)") != 1:
        raise RuntimeError("QR source changed unexpectedly")

    backup_dir = Path(__file__).resolve().parents[2] / ".wts_print_format_backups"
    backup_dir.mkdir(exist_ok=True)
    backup = backup_dir / (
        "Warehouse_Transfer_Slip_before_QR_64px_"
        + datetime.now().strftime("%Y%m%d_%H%M%S")
        + ".html"
    )
    backup.write_text(original, encoding="utf-8")
    fmt.html = updated
    fmt.save(ignore_permissions=True)
    frappe.db.commit()
    frappe.clear_cache()
    print(f"WTS QR resized to 64 x 64 px. Backup: {backup}")
    return {"changed": True, "backup": str(backup)}
