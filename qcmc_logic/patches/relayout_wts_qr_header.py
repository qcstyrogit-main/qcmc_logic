"""Place WTS number below the company title and a compact QR at top right.

Run:
bench --site erp.qcstyro.local execute qcmc_logic.patches.relayout_wts_qr_header.execute

Backs up live Print Format, preserves REPRINTED and other slip content.
"""
from datetime import datetime
from pathlib import Path
import re

import frappe


FORMAT = "Warehouse Transfer Slip"
MARKER = "qcmc-wts-header-qr"


def execute():
    from qcmc_logic.wts_qr import get_wts_qr_svg

    if 'class="qcmc-wts-qr"' not in str(get_wts_qr_svg("QC-SC-FGWT26-00001")):
        raise RuntimeError("QR renderer preflight failed; no changes made")

    fmt = frappe.get_doc("Print Format", FORMAT)
    original = fmt.html or ""
    if MARKER in original:
        print("WTS header already rearranged; no changes made")
        return {"changed": False, "reason": "already_installed"}

    # The original header includes a company/subtitle cell, a REPRINTED cell,
    # and a right-hand WTS # cell. Work only within that table.
    header = re.search(
        r'<table\s+class="header-table"[^>]*>.*?</table>',
        original, flags=re.S | re.I
    )
    if not header:
        raise RuntimeError("Warehouse Transfer header table missing; no changes made")
    header_html = header.group()

    subtitle_pattern = r'(<div\s+class="subtitle"[^>]*>\s*\{\{\s*document_title\s*\}\}\s*</div>)'
    wts_pattern = (
        r'<td\s+style="width:\s*38%;"\s+class="docno">'
        r'\s*<span\s+class="label">WTS #:</span>\s*'
        r'\{\{\s*doc\.name\s*\}\}\s*</td>'
    )
    if len(re.findall(subtitle_pattern, header_html)) != 1:
        raise RuntimeError("Company subtitle not found uniquely; no changes made")
    if len(re.findall(wts_pattern, header_html)) != 1:
        raise RuntimeError("Existing WTS number cell not found uniquely; no changes made")

    # Source QR may be beneath From/To or still in the previous barcode row.
    relocated = original
    left_qr_pattern = re.compile(
        r'\s*<div\s+class="qcmc-wts-qr-under-from-to"[^>]*>\s*'
        r'\{\{\s*get_wts_qr_svg\(doc\.name\)\s*\}\}\s*</div>',
        flags=re.S
    )
    relocated, left_count = left_qr_pattern.subn("", relocated)
    header_qr_pattern = re.compile(
        r'\s*<tr\s+class="qcmc-wts-scanner-row"[^>]*>'
        r'(?:(?!</tr>).)*?\{\{\s*get_wts_qr_svg\(doc\.name\)\s*\}\}'
        r'(?:(?!</tr>).)*?</tr>', flags=re.S
    )
    relocated, row_count = header_qr_pattern.subn("", relocated)
    if left_count + row_count != 1:
        raise RuntimeError(
            "Expected one existing WTS QR placement; no changes made "
            f"(left={left_count}, header={row_count})"
        )
    header = re.search(
        r'<table\s+class="header-table"[^>]*>.*?</table>',
        relocated, flags=re.S | re.I
    )
    header_html = header.group()

    # Keep the printed WTS number exactly the document ID, below the subtitle.
    number_line = (
        '<div class="qcmc-wts-number-under-title" '
        'style="font-size:8pt;margin-top:4px;white-space:nowrap;">'
        '<span class="label">WTS #:</span> {{ doc.name }}</div>'
    )
    new_header, subtitle_count = re.subn(
        subtitle_pattern,
        lambda match: match.group(1) + '\n        ' + number_line,
        header_html,
        count=1,
    )
    if subtitle_count != 1:
        raise RuntimeError("Could not relocate WTS number")

    # Compact QR takes the original top-right WTS cell. Keep both its quiet
    # zone and the CSS width at 96px (about 25mm when printed at 100%).
    qr_cell = (
        '<td style="width: 38%;text-align:right;vertical-align:top;" '
        'class="docno">'
        '<div class="' + MARKER + '" '
        'style="display:inline-block;width:96px;height:96px;'
        'background:#fff;line-height:0;page-break-inside:avoid;">'
        '{{ get_wts_qr_svg(doc.name) }}</div>'
        '</td>'
    )
    new_header, number_count = re.subn(
        wts_pattern, lambda _: qr_cell, new_header, count=1
    )
    if number_count != 1:
        raise RuntimeError("Could not replace former WTS position with QR")
    updated = relocated[:header.start()] + new_header + relocated[header.end():]

    if (
        updated.count("get_wts_qr_svg(doc.name)") != 1
        or updated.count('class="qcmc-wts-number-under-title"') != 1
        or updated.count(MARKER) != 1
        or updated.count("WTS #:") != 1
    ):
        raise RuntimeError("Header transformation validation failed; no changes made")

    backup_dir = Path(__file__).resolve().parents[2] / ".wts_print_format_backups"
    backup_dir.mkdir(exist_ok=True)
    backup = backup_dir / (
        "Warehouse_Transfer_Slip_before_header_relayout_"
        + datetime.now().strftime("%Y%m%d_%H%M%S") + ".html"
    )
    backup.write_text(original, encoding="utf-8")

    fmt.html = updated
    fmt.save(ignore_permissions=True)
    frappe.db.commit()
    frappe.clear_cache()
    print(f"Moved WTS number under company, compact QR to top right. Backup: {backup}")
    return {"changed": True, "backup": str(backup), "format": FORMAT}
