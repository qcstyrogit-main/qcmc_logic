"""Reduce WTS barcode width in live Print Format after checksum correction.

Run once:
bench --site erp.qcstyro.local execute qcmc_logic.patches.resize_wts_barcode.execute
No migration, no changes to Warehouse Transfer documents.
"""
from datetime import datetime
from pathlib import Path
import frappe


def execute():
    fmt = frappe.get_doc("Print Format", "Warehouse Transfer Slip")
    original = fmt.html or ""
    marker = 'class="qcmc-wts-scanner-row"'
    if original.count(marker) != 1:
        raise RuntimeError("Expected exactly one WTS barcode header row; no changes made")

    start = original.index(marker)
    end = original.find("</tr>", start)
    if end < 0:
        raise RuntimeError("Cannot find end of WTS barcode row")
    section = original[start:end]
    if "width:390px" in section and "width:520px" not in section:
        print("Barcode already resized to 390px")
        return {"changed": False}
    if section.count("width:520px") != 1 or "get_wts_code128_svg(doc.name)" not in section:
        raise RuntimeError("Unexpected barcode row markup; no changes made")

    edited_section = section.replace("width:520px", "width:390px", 1)
    updated = original[:start] + edited_section + original[end:]
    backup_dir = Path(__file__).resolve().parents[2] / ".wts_print_format_backups"
    backup_dir.mkdir(exist_ok=True)
    backup = backup_dir / ("Warehouse_Transfer_Slip_before_resize_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".html")
    backup.write_text(original, encoding="utf-8")
    fmt.html = updated
    fmt.save(ignore_permissions=True)
    frappe.db.commit()
    frappe.clear_cache()
    print("WTS CODE128 barcode resized to 390px; corrected encoder will render on refresh.")
    return {"changed": True, "backup": str(backup)}
