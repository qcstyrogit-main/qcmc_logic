"""Compact existing Warehouse Transfer Slip CODE128 barcode row.

Run:
bench --site erp.qcstyro.local execute qcmc_logic.patches.compact_wts_barcode.execute

Modifies only the inline barcode wrapper width and row padding. Backs up
the original print HTML. Safe to rerun.
"""
from pathlib import Path
from datetime import datetime
import re

import frappe


def execute():
    fmt = frappe.get_doc("Print Format", "Warehouse Transfer Slip")
    original = fmt.html or ""
    marker = 'class="qcmc-wts-scanner-row"'
    if original.count(marker) != 1:
        raise RuntimeError("Expected one WTS barcode row; no changes made")
    start = original.index(marker)
    end = original.find("</tr>", start)
    if end < 0:
        raise RuntimeError("Barcode row close tag missing; no changes made")
    section = original[start:end]
    if section.count("get_wts_code128_svg(doc.name)") != 1:
        raise RuntimeError("Barcode rendering call missing or duplicated")
    if "width:300px" in section and "padding:3px 0 5px" in section:
        print("WTS barcode already compact")
        return {"changed": False}
    width_match = re.findall(r"width:(?:520|390)px", section)
    if len(width_match) != 1:
        raise RuntimeError("Unexpected barcode wrapper width; no changes made")
    replacement = section.replace(width_match[0], "width:300px", 1)
    replacement = replacement.replace("padding:5px 0 9px", "padding:3px 0 5px", 1)
    updated = original[:start] + replacement + original[end:]
    backup_dir = Path(__file__).resolve().parents[2] / ".wts_print_format_backups"
    backup_dir.mkdir(exist_ok=True)
    backup = backup_dir / ("Warehouse_Transfer_Slip_before_compact_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".html")
    backup.write_text(original, encoding="utf-8")
    fmt.html = updated
    fmt.save(ignore_permissions=True)
    frappe.db.commit()
    frappe.clear_cache()
    print("WTS barcode reduced to 300 x 34 px; original print format backed up.")
    return {"changed": True, "backup": str(backup)}
