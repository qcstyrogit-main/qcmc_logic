import re
import frappe
import json
from collections import defaultdict


def _resolve_warehouse(raw_name):
    """Find the ERPNext warehouse that best matches the scanner's stockroom value.

    The scanner encodes warehouse as e.g. 'Stockroom-Guyong' while ERPNext
    stores it as 'Stockroom - Guyong'.  Try exact → normalised → LIKE search.
    """
    raw = raw_name.strip()
    if not raw:
        return None

    # 1. Exact match
    if frappe.db.exists("Warehouse", raw):
        return raw

    # 2. Normalise spacing around dashes: 'Stockroom-Guyong' → 'Stockroom - Guyong'
    normalised = re.sub(r"\s*-\s*", " - ", raw)
    if frappe.db.exists("Warehouse", normalised):
        return normalised

    # 3. LIKE search — find any active warehouse whose name contains the raw value
    match = frappe.db.get_value(
        "Warehouse",
        {"name": ["like", f"%{raw}%"], "disabled": 0},
        "name",
    )
    if match:
        return match

    # 4. LIKE search using normalised form
    match = frappe.db.get_value(
        "Warehouse",
        {"name": ["like", f"%{normalised}%"], "disabled": 0},
        "name",
    )
    return match or None


def _batch_exists(batch_no, item_code):
    """Return True if the batch exists for the given item."""
    if not batch_no:
        return False
    return bool(frappe.db.exists("Batch", {"name": batch_no, "item": item_code}))


@frappe.whitelist()
def submit_pcount_entries(reconciliation_id, entries):
    """Replace Stock Reconciliation items with summarized P. Count scan data from the scanner app."""
    if frappe.session.user == "Guest":
        frappe.local.response["http_status_code"] = 401
        return {"success": False, "message": "Session expired. Please log in again."}

    try:
        if not reconciliation_id:
            frappe.throw("Reconciliation ID is required")

        if isinstance(entries, str):
            entries = json.loads(entries)

        if not isinstance(entries, list):
            frappe.throw("Entries must be a list")

        doc = frappe.get_doc("Stock Reconciliation", reconciliation_id)

        if doc.docstatus != 0:
            frappe.local.response["http_status_code"] = 400
            return {
                "success": False,
                "message": f"Stock Reconciliation '{reconciliation_id}' is not in Draft status and cannot be modified",
            }

        # Group entries by (item_code, warehouse, batch_no) and sum quantities
        grouped = defaultdict(float)
        device_map = {}
        skipped = []

        for entry in entries:
            item_code = (entry.get("itemCode") or "").strip()
            bin_data = entry.get("bin") or {}
            raw_warehouse = (bin_data.get("stockroom") or "").strip()
            batch_no = (entry.get("lotNo") or "").strip()
            device_id = (entry.get("deviceId") or "").strip()
            quantity = float(entry.get("quantity") or 0)

            if not item_code or not raw_warehouse or quantity <= 0:
                continue

            warehouse = _resolve_warehouse(raw_warehouse)
            if not warehouse:
                skipped.append(f"{item_code} (unknown warehouse: {raw_warehouse})")
                continue

            # Use batch only if it exists for this item; otherwise record without batch
            resolved_batch = batch_no if _batch_exists(batch_no, item_code) else ""

            key = (item_code, warehouse, resolved_batch)
            grouped[key] += quantity
            if key not in device_map:
                device_map[key] = device_id

        if not grouped:
            skipped_msg = "; ".join(skipped[:3])
            frappe.local.response["http_status_code"] = 400
            return {
                "success": False,
                "message": f"No valid entries to submit. Skipped: {skipped_msg}" if skipped_msg else "No valid entries to submit",
            }

        # Rebuild items table with grouped scan data
        doc.items = []
        for (item_code, warehouse, batch_no), qty in grouped.items():
            row = doc.append("items", {})
            row.item_code = item_code
            row.warehouse = warehouse
            row.qty = qty
            if batch_no:
                row.batch_no = batch_no
            scanned_device = device_map.get((item_code, warehouse, batch_no), "")
            if scanned_device:
                row.custom_scanned_device = scanned_device

        doc.save(ignore_permissions=True)
        frappe.db.commit()

        result = {
            "success": True,
            "message": f"Updated {len(grouped)} item(s) in {reconciliation_id}",
            "reconciliation_id": reconciliation_id,
            "item_count": len(grouped),
        }
        if skipped:
            result["skipped"] = skipped

        return result

    except frappe.DoesNotExistError:
        frappe.local.response["http_status_code"] = 404
        return {"success": False, "message": f"Stock Reconciliation '{reconciliation_id}' not found"}

    except frappe.PermissionError:
        frappe.local.response["http_status_code"] = 403
        return {"success": False, "message": "You do not have permission to modify this document"}

    except Exception:
        frappe.log_error(frappe.get_traceback(), "stock_reconciliation.submit_pcount_entries")
        frappe.local.response["http_status_code"] = 500
        return {"success": False, "message": "Failed to submit entries. Check server logs for details."}
