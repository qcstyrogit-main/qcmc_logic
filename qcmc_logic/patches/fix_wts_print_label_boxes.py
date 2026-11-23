"""Remove framework label badges from Warehouse Transfer Slip print preview.

Run once:
  bench --site erp.qcstyro.local execute qcmc_logic.patches.fix_wts_print_label_boxes.execute

Only renames the local HTML/CSS label class. Item table borders, QR,
REPRINTED heading, and transaction values remain unchanged.
"""
from datetime import datetime
from pathlib import Path

import frappe

FORMAT_NAME = "Warehouse Transfer Slip"
OLD_CLASS = '<span class="label">'
NEW_CLASS = '<span class="wts-text-label">'
OLD_RULE = ".label { font-weight: 700; }"
NEW_RULE = ".wts-print .wts-text-label { font-weight: 700; background: none; border: 0; outline: 0; box-shadow: none; padding: 0; border-radius: 0; color: #000; font-size: inherit; line-height: inherit; }"


def execute():
    fmt = frappe.get_doc("Print Format", FORMAT_NAME)
    original = fmt.html or ""

    if NEW_CLASS in original and OLD_CLASS not in original:
        print("WTS print labels already use plain text styling; no changes")
        return {"changed": False, "reason": "already_installed"}

    old_count = original.count(OLD_CLASS)
    if old_count < 3 or original.count(OLD_RULE) != 1:
        raise RuntimeError(
            f"Unexpected print label markup ({old_count} spans, "
            f"{original.count(OLD_RULE)} CSS rules); no changes made"
        )

    updated = original.replace(OLD_CLASS, NEW_CLASS).replace(OLD_RULE, NEW_RULE, 1)
    if updated.count(NEW_CLASS) != old_count or OLD_CLASS in updated or OLD_RULE in updated:
        raise RuntimeError("Print label replacement validation failed")

    backup_dir = Path(__file__).resolve().parents[2] / ".wts_print_format_backups"
    backup_dir.mkdir(exist_ok=True)
    backup = backup_dir / (
        "Warehouse_Transfer_Slip_before_label_fix_"
        + datetime.now().strftime("%Y%m%d_%H%M%S")
        + ".html"
    )
    backup.write_text(original, encoding="utf-8")

    fmt.html = updated
    fmt.save(ignore_permissions=True)
    frappe.db.commit()
    frappe.clear_cache()
    print(f"WTS label borders removed. Original backed up: {backup}")
    return {"changed": True, "labels_updated": old_count, "backup": str(backup)}
