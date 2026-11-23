"""Move WTS CODE128 to an unconstrained header row (one-time, idempotent).

Run: bench --site erp.qcstyro.local execute qcmc_logic.patches.fix_wts_barcode_print_size.execute
Does not migrate or change Warehouse Transfer documents.
"""
import re
from datetime import datetime
from pathlib import Path
import frappe

FORMAT = "Warehouse Transfer Slip"
MARKER = "qcmc-wts-scanner-row"
EXISTING_MARKER = "qcmc-wts-barcode-container"


def execute():
    fmt = frappe.get_doc("Print Format", FORMAT)
    original = fmt.html or ""
    if MARKER in original:
        print("WTS scanner barcode already positioned in full-width header; no changes")
        return {"changed": False, "reason": "already_installed"}
    if not original or original.count(EXISTING_MARKER) != 1:
        raise RuntimeError("Expected exactly one previously inserted WTS barcode; no changes made")

    pattern = re.compile(
        r'\s*<div class="qcmc-wts-barcode-container"[^>]*>\s*'
        r'\{\{\s*get_wts_code128_svg\(doc\.name\)\s*\}\}\s*</div>'
    )
    cleaned, found = pattern.subn("", original)
    if found != 1:
        raise RuntimeError("Existing barcode markup not matched safely; no changes made")

    header = re.search(
        r'(<table\s+class="header-table"[^>]*>)(.*?)(</table>)',
        cleaned,
        flags=re.S | re.I,
    )
    if not header or header.group(2).count("WTS #:") != 1 or "{{ doc.name }}" not in header.group(2):
        raise RuntimeError("WTS header layout has changed; no changes made")

    header_body = header.group(2)
    # Insert one barcode-only table row immediately after the document header.
    # Keep the WTS text and REPRINTED label as they were.
    row_end = re.search(r"</tr\s*>", header_body, flags=re.I)
    if not row_end:
        raise RuntimeError("Header closing row not found")
    barcode_row = (
        '\n    <tr class="' + MARKER + '">'
        '<td colspan="3" style="padding:5px 0 9px;text-align:right;white-space:normal;">'
        '<div style="display:inline-block;width:520px;max-width:100%;line-height:0;">'
        '{{ get_wts_code128_svg(doc.name) }}</div></td></tr>'
    )
    new_body = header_body[:row_end.end()] + barcode_row + header_body[row_end.end():]
    updated_header = header.group(1) + new_body + header.group(3)
    updated = cleaned[:header.start()] + updated_header + cleaned[header.end():]
    if updated.count("get_wts_code128_svg(doc.name)") != 1:
        raise RuntimeError("Barcode placement validation failed")

    backup_dir = Path(__file__).resolve().parents[2] / ".wts_print_format_backups"
    backup_dir.mkdir(exist_ok=True)
    backup = backup_dir / ("Warehouse_Transfer_Slip_before_scanner_fix_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".html")
    backup.write_text(original, encoding="utf-8")
    fmt.html = updated
    fmt.save(ignore_permissions=True)
    frappe.db.commit()
    frappe.clear_cache()
    print(f"Updated barcode: full-width 520px CODE128. Backup: {backup}")
    return {"changed": True, "backup": str(backup), "format": FORMAT}
