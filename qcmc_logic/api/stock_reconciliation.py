import re
import frappe
import json
from collections import defaultdict
from frappe.auth import LoginManager
from erpnext.stock.utils import get_stock_balance


def _safe_float(value, default=0.0):
    try:
        return float(value or 0)
    except Exception:
        return float(default)


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


def _row_location_key(row):
    return (
        row.item_code or "",
        row.warehouse or "",
        row.batch_no or "",
        row.bldg or "",
        row.aisle or "",
        row.rack or "",
        row.bin or "",
    )


def _merge_device_names(*values):
    devices = []
    seen = set()

    for value in values:
        for device in (value or "").split(","):
            cleaned = device.strip()
            if cleaned and cleaned not in seen:
                devices.append(cleaned)
                seen.add(cleaned)

    return ", ".join(devices)[:140]


def _extract_mobile_token(mobile_token=None):
    token = str(mobile_token or "").strip()
    if token:
        return token

    form_token = str(frappe.form_dict.get("mobile_token") or "").strip()
    if form_token:
        return form_token

    request = getattr(frappe.local, "request", None)
    if request:
        try:
            payload = request.get_json(silent=True) or {}
        except Exception:
            payload = {}

        if isinstance(payload, dict):
            json_token = str(payload.get("mobile_token") or "").strip()
            if json_token:
                return json_token

    return ""


def _resolve_mobile_token_user(token):
    if not token:
        return None
    import hashlib
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return frappe.cache.get_value(f"qcmc_scanner_mobile_token:{digest}") or None


def _authenticate_request_user(mobile_token=None):
    if frappe.session.user != "Guest":
        return frappe.session.user

    token = _extract_mobile_token(mobile_token)
    user = _resolve_mobile_token_user(token)
    if not user:
        return None

    login_manager = LoginManager()
    login_manager.login_as(user)
    frappe.db.commit()
    return frappe.session.user


def _get_item_defaults(item_code):
    item = frappe.db.get_value(
        "Item",
        item_code,
        ["item_name", "item_group", "stock_uom", "valuation_rate"],
        as_dict=True,
    ) or {}
    return {
        "item_name": item.get("item_name") or item_code,
        "item_group": item.get("item_group") or "",
        "stock_uom": item.get("stock_uom") or "",
        "item_valuation_rate": _safe_float(item.get("valuation_rate")),
    }


def _get_row_valuation_context(item_code, warehouse, posting_date, posting_time):
    current_qty = 0.0
    current_valuation_rate = 0.0

    if item_code and warehouse:
        try:
            balance = get_stock_balance(
                item_code,
                warehouse,
                posting_date,
                posting_time,
                with_valuation_rate=True,
            )
            if isinstance(balance, (list, tuple)):
                current_qty = _safe_float(balance[0])
                current_valuation_rate = _safe_float(balance[1])
            else:
                current_qty = _safe_float(balance)
        except Exception:
            current_qty = 0.0
            current_valuation_rate = 0.0

    return current_qty, current_valuation_rate


def _apply_item_fields(row, doc):
    item_defaults = _get_item_defaults(row.item_code)
    current_qty, current_valuation_rate = _get_row_valuation_context(
        row.item_code,
        row.warehouse,
        doc.posting_date,
        doc.posting_time,
    )

    row.item_name = item_defaults["item_name"]
    row.item_group = item_defaults["item_group"]
    row.stock_uom = item_defaults["stock_uom"]
    row.current_qty = current_qty
    row.current_valuation_rate = current_valuation_rate
    row.current_amount = current_qty * current_valuation_rate

    valuation_rate = _safe_float(row.get("valuation_rate"))
    if not valuation_rate:
        valuation_rate = current_valuation_rate or _safe_float(item_defaults["item_valuation_rate"])
    row.valuation_rate = valuation_rate
    qty = _safe_float(row.qty)
    row.amount = qty * valuation_rate
    row.quantity_difference = qty - current_qty
    row.amount_difference = row.amount - row.current_amount


def _consolidate_duplicate_location_rows(doc):
    consolidated = {}
    ordered_rows = []

    for row in doc.items:
        key = _row_location_key(row)
        existing = consolidated.get(key)

        if not existing:
            consolidated[key] = row
            ordered_rows.append(row)
            continue

        existing.qty = _safe_float(existing.qty) + _safe_float(row.qty)
        existing.custom_scanned_device = _merge_device_names(
            existing.get("custom_scanned_device"),
            row.get("custom_scanned_device"),
        )

    doc.items = []
    for row in ordered_rows:
        doc.append("items", row.as_dict())


@frappe.whitelist(allow_guest=True)
def submit_pcount_entries(reconciliation_id, entries, mobile_token=None):
    """Upsert summarized P. Count scan data without removing other devices' rows."""
    user = _authenticate_request_user(mobile_token)
    if user == "Guest" or not user:
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

        # ERPNext normally allows only one row per item/warehouse/batch.
        # Our override allows separate rows when the scanned bin location is
        # different, so include location fields in the merge key.
        grouped = defaultdict(float)
        grouped_devices = defaultdict(set)
        skipped = []
        duplicate_devices = []

        for entry in entries:
            item_code = (entry.get("itemCode") or "").strip()
            bin_data = entry.get("bin") or {}
            raw_warehouse = (bin_data.get("stockroom") or "").strip()
            batch_no = (entry.get("lotNo") or "").strip()
            device_id = (entry.get("deviceId") or "").strip()
            quantity = _safe_float(entry.get("quantity"))

            if not item_code or not raw_warehouse or quantity <= 0:
                continue

            warehouse = _resolve_warehouse(raw_warehouse)
            if not warehouse:
                skipped.append(f"{item_code} (unknown warehouse: {raw_warehouse})")
                continue

            # Use batch only if it exists for this item; otherwise record without batch
            resolved_batch = batch_no if _batch_exists(batch_no, item_code) else ""

            location_key = (
                (bin_data.get("building") or "").strip(),
                (bin_data.get("aisle") or "").strip(),
                (bin_data.get("rack") or "").strip(),
                (bin_data.get("bin") or "").strip(),
            )
            key = (item_code, warehouse, resolved_batch, *location_key)
            grouped[key] += quantity
            if device_id:
                grouped_devices[key].add(device_id)

        if not grouped:
            skipped_msg = "; ".join(skipped[:3])
            frappe.local.response["http_status_code"] = 400
            return {
                "success": False,
                "message": f"No valid entries to submit. Skipped: {skipped_msg}" if skipped_msg else "No valid entries to submit",
            }

        existing_rows = {}
        for row in doc.items:
            existing_key = _row_location_key(row)
            if existing_key not in existing_rows:
                existing_rows[existing_key] = row

        inserted = 0
        updated = 0
        for (item_code, warehouse, batch_no, building, aisle, rack, bin_name), qty in grouped.items():
            key = (item_code, warehouse, batch_no, building, aisle, rack, bin_name)
            row = existing_rows.get(key)
            incoming_devices = grouped_devices.get(key, set())

            if row:
                existing_devices = {
                    device.strip()
                    for device in (row.get("custom_scanned_device") or "").split(",")
                    if device.strip()
                }
                repeated_devices = existing_devices.intersection(incoming_devices)

                if repeated_devices:
                    duplicate_devices.extend(sorted(repeated_devices))
                    continue

                row.qty = _safe_float(row.qty) + qty
                merged_devices = sorted(existing_devices.union(incoming_devices))
                if merged_devices:
                    row.custom_scanned_device = _merge_device_names(", ".join(merged_devices))
                row.bldg = building
                row.aisle = aisle
                row.rack = rack
                row.bin = bin_name
                _apply_item_fields(row, doc)
                updated += 1
            else:
                row = doc.append("items", {})
                row.item_code = item_code
                row.warehouse = warehouse
                row.qty = qty
                if batch_no:
                    row.batch_no = batch_no
                row.bldg = building
                row.aisle = aisle
                row.rack = rack
                row.bin = bin_name
                if incoming_devices:
                    row.custom_scanned_device = _merge_device_names(", ".join(sorted(incoming_devices)))
                _apply_item_fields(row, doc)
                inserted += 1

        _consolidate_duplicate_location_rows(doc)
        for row in doc.items:
            _apply_item_fields(row, doc)
        doc.flags.ignore_links = True

        doc.save(ignore_permissions=True)
        frappe.db.commit()

        result = {
            "success": True,
            "message": f"Submitted {len(grouped)} item(s) to {reconciliation_id} ({inserted} added, {updated} updated)",
            "reconciliation_id": reconciliation_id,
            "item_count": len(grouped),
            "inserted": inserted,
            "updated": updated,
        }
        if skipped:
            result["skipped"] = skipped
        if duplicate_devices:
            result["duplicate_devices"] = sorted(set(duplicate_devices))

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
