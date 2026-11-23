"""Move Warehouse Transfer Slip QR beneath From / To in the left metadata cell.

Apply once:
 bench --site erp.qcstyro.local execute qcmc_logic.patches.move_wts_qr_under_from_to.execute

Backs up the current Print Format HTML. Does not modify warehouse transactions.
"""
from datetime import datetime
from pathlib import Path
import re
import frappe

FORMAT_NAME = "Warehouse Transfer Slip"
LOCATION_MARKER = "qcmc-wts-qr-under-from-to"
ROW_MARKER = "qcmc-wts-scanner-row"


def execute():
    fmt = frappe.get_doc("Print Format", FORMAT_NAME)
    original = fmt.html or ""
    if LOCATION_MARKER in original:
        print("WTS QR already beneath From / To; nothing to change")
        return {"changed": False}
    if original.count(ROW_MARKER) != 1 or original.count("get_wts_qr_svg(doc.name)") != 1:
        raise RuntimeError("Existing WTS QR header not found uniquely; print format unchanged")

    # Remove only the existing dedicated header QR row, leaving the WTS number,
    # company, and REPRINTED heading intact.
    row_pattern = re.compile(
        r'<tr\s+class="qcmc-wts-scanner-row"\s*>'
        r'(?:(?!</tr>).)*?'
        r'\{\{\s*get_wts_qr_svg\(doc\.name\)\s*\}\}'
        r'(?:(?!</tr>).)*?</tr>',
        flags=re.S,
    )
    without_row, removed_count = row_pattern.subn("", original)
    if removed_count != 1:
        raise RuntimeError("QR header row mismatch; print format unchanged")

    # Locate the first, unclassified left TD in meta-table. Its content already
    # contains From/To, and optionally Reference Document No.
    start = without_row.find('<table class="meta-table">')
    if start < 0:
        raise RuntimeError("Warehouse metadata table not found; no changes made")
    next_table = without_row.find('</table>', start)
    if next_table < 0:
        raise RuntimeError("Metadata table end not found; no changes made")
    left_start = without_row.find("<td>", start, next_table)
    left_end = without_row.find("</td>", left_start, next_table)
    if left_start < 0 or left_end < 0:
        raise RuntimeError("From/To metadata cell not found; no changes made")
    left_content = without_row[left_start:left_end]
    if "From :" not in left_content or "To :" not in left_content:
        raise RuntimeError("Expected From and To labels in left cell; no changes made")

    # Put the QR within blank space below left-side transaction metadata.
    qr_block = (
        '\n        <div class="qcmc-wts-qr-under-from-to" '
        'style="width:112px;height:112px;margin:8px 0 3px 2px;'
        'padding:0;line-height:0;background:#fff;page-break-inside:avoid;">'
        '{{ get_wts_qr_svg(doc.name) }}'
        '</div>\n      '
    )
    updated = without_row[:left_end] + qr_block + without_row[left_end:]
    if (
        updated.count("get_wts_qr_svg(doc.name)") != 1
        or ROW_MARKER in updated
        or updated.count(LOCATION_MARKER) != 1
    ):
        raise RuntimeError("QR relocation check failed; no changes made")

    backup_dir = Path(__file__).resolve().parents[2] / ".wts_print_format_backups"
    backup_dir.mkdir(exist_ok=True)
    backup = backup_dir / (
        "Warehouse_Transfer_Slip_before_QR_reposition_"
        + datetime.now().strftime("%Y%m%d_%H%M%S")
        + ".html"
    )
    backup.write_text(original, encoding="utf-8")

    fmt.html = updated
    fmt.save(ignore_permissions=True)
    frappe.db.commit()
    frappe.clear_cache()
    print(f"Moved WTS QR beneath From / To; backup: {backup}")
    return {"changed": True, "backup": str(backup), "format": FORMAT_NAME}
