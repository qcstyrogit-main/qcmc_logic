import re
import frappe
import json
import hashlib
import math
import uuid
from collections import defaultdict
from frappe.utils import cint, get_datetime, now_datetime, nowdate
from erpnext.stock.utils import get_stock_balance
from qcmc_logic.overrides.putaway_rule_dimension import get_dimension_stock_balance
from qcmc_logic.physical_count_grouping import (
    aggregate_physical_count_locations,
    latest_physical_count_groups,
    normalize_inventory_tag,
    physical_count_group_key,
)
from qcmc_logic.utils import ensure_scanner_warehouse_access
from qcmc_logic.api.mobile_auth import extract_mobile_token, resolve_device_token_user

def _safe_float(value, default=0.0):
    try:
        return float(value or 0)
    except Exception:
        return float(default)


def _effective_physical_count(row):
    recount = row.get("cost_acct_cnt")
    if recount is None or str(recount).strip() in {"", "0.000000000"}:
        return _safe_float(row.physical_count)
    return _safe_float(recount)


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


def _warehouse_identity(value):
    """Canonical comparison key for legacy scanner warehouse labels."""
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


def _row_location_key(row):
    return (
        (row.item_code or "").strip(),
        (row.warehouse or "").strip(),
        (row.get("location") or "").strip(),
        (row.get("stock_uom") or "").strip(),
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


def _resolve_storage_location(entry):
    bin_data = entry.get("bin") or {}
    if not isinstance(bin_data, dict):
        frappe.throw("bin must be an object")
    location_id = str(
        entry.get("inventoryLocation")
        or entry.get("inventory_location")
        or bin_data.get("locationId")
        or bin_data.get("location_id")
        or entry.get("storageLocation")
        or entry.get("storage_location")
        or ""
    ).strip()
    if not location_id:
        return None

    location = frappe.db.get_value(
        "Storage Location",
        {"name": location_id, "disabled": 0},
        ["name", "location_type", "full_path", "custom_warehouse"],
        as_dict=True,
    )
    if not location:
        frappe.throw(f"Storage Location '{location_id}' does not exist or is disabled")

    return location


def _validate_storage_location_warehouse(location, warehouse, row_number=None):
    """Require the exact Storage Location to belong to the exact Warehouse."""
    prefix = f"Entry #{row_number}: " if row_number else ""
    location_warehouse = str(location.get("custom_warehouse") or "").strip()
    if not location_warehouse:
        frappe.throw(
            f"{prefix}Storage Location '{location.name}' has no authoritative Warehouse."
        )
    if location_warehouse != str(warehouse or "").strip():
        frappe.throw(
            f"{prefix}Storage Location '{location.name}' belongs to Warehouse "
            f"'{location_warehouse}', not '{warehouse}'."
        )


class PhysicalCountConflict(frappe.ValidationError):
    def __init__(self, current_quantity, entry=None):
        self.current_quantity = current_quantity
        self.entry = entry or frappe._dict()
        super().__init__("ERP stock changed after this count was synchronized. Refresh and review.")


class PhysicalCountNotOpen(frappe.ValidationError):
    pass


def _ensure_pcount_open_for_scanning(doc):
    workflow_state = str(doc.get("workflow_state") or "").strip()
    if doc.docstatus != 0 or workflow_state in {"For Recon", "Close Inventory"}:
        raise PhysicalCountNotOpen(
            f"Stock Reconciliation '{doc.name}' is no longer open for scanner activity."
        )


def _current_inventory_quantity(item_code, warehouse, storage_location, batch_no=None, serial_no=None):
    """Authoritative physical-location balance from counts, allocations, and transfers."""
    item_code = str(item_code or "").strip()
    warehouse = str(warehouse or "").strip()
    storage_location = str(storage_location or "").strip()
    latest_count = frappe.db.sql(
        """
        with ranked_groups as (
            select pcr.*,
                   coalesce(pcr.submitted_at, sr.modified) as group_counted_at,
                   row_number() over (
                       partition by pcr.item_code, pcr.warehouse,
                           coalesce(nullif(pcr.location, ''), pcr.inventory_location),
                           coalesce(pcr.batch_no, ''), coalesce(pcr.serial_no, ''),
                           coalesce(pcr.uom, ''), coalesce(pcr.inventory_tag, '')
                       order by coalesce(pcr.submitted_at, sr.modified) desc, pcr.idx desc
                   ) as row_rank
            from `tabQCMC Physical Count Result` pcr
            inner join `tabStock Reconciliation` sr on sr.name = pcr.parent
            where sr.docstatus = 1 and sr.custom_physical_count = 1
              and pcr.item_code = %s and pcr.warehouse = %s
              and coalesce(nullif(pcr.location, ''), pcr.inventory_location) = %s
              and coalesce(pcr.batch_no, '') = %s
              and coalesce(pcr.serial_no, '') = %s
        )
        select sum(coalesce(cast(nullif(nullif(cost_acct_cnt, ''), '0.000000000') as decimal(21,9)), physical_count)) as physical_count,
               max(group_counted_at) as counted_at
        from ranked_groups where row_rank = 1
        """,
        (
            item_code, warehouse, storage_location,
            str(batch_no or "").strip(), str(serial_no or "").strip(),
        ), as_dict=True,
    )
    latest_count = latest_count if latest_count and latest_count[0].counted_at else []
    cutoff = latest_count[0].counted_at if latest_count else None
    allocation_state = frappe.db.sql(
        """
        select coalesce(sum(wal.actual_qty), 0) as quantity, count(*) as row_count
        from `tabWarehouse Allocation Location` wal
        inner join `tabWarehouse Allocation` wa on wa.name = wal.parent
        where wa.docstatus = 1 and wa.status = 'Completed'
          and wa.warehouse = %s and wal.item_code = %s
          and wal.status = 'VERIFIED' and wal.actual_location = %s
          and (%s is null or coalesce(wa.completed_at, wa.modified) > %s)
        """,
        (warehouse, item_code, storage_location, cutoff, cutoff), as_dict=True,
    )[0]
    allocation = allocation_state.quantity or 0
    movement = frappe.db.sql(
        """
        select coalesce(sum(case when target_location = %s then quantity else 0 end), 0)
             - coalesce(sum(case when source_location = %s then quantity else 0 end), 0)
        from `tabLocation Transfer`
        where docstatus = 1 and warehouse = %s and item_code = %s
          and (%s is null or transferred_at > %s)
        """,
        (storage_location, storage_location, warehouse, item_code, cutoff, cutoff),
    )[0][0] or 0
    if latest_count:
        return _safe_float(latest_count[0].physical_count) + _safe_float(allocation) + _safe_float(movement)
    if allocation_state.row_count:
        return _safe_float(allocation) + _safe_float(movement)
    legacy_balance = get_dimension_stock_balance(
        item_code, warehouse, {"location": storage_location},
        batch_no=str(batch_no or "").strip() or None,
        serial_no=str(serial_no or "").strip() or None,
    )
    return _safe_float(legacy_balance) + _safe_float(movement)


def _quantities_equal(left, right):
    precision = cint(frappe.db.get_default("float_precision")) or 3
    tolerance = 0.5 * (10 ** -precision)
    return math.isclose(_safe_float(left), _safe_float(right), rel_tol=0, abs_tol=tolerance)


def _extract_mobile_token(mobile_token=None):
    return extract_mobile_token(mobile_token)


def _resolve_mobile_token_user(token):
    return resolve_device_token_user(token)


def _authenticate_request_user(mobile_token=None):
    token = _extract_mobile_token(mobile_token)
    if token:
        user = _resolve_mobile_token_user(token)
        if not user:
            return None
    elif frappe.session.user != "Guest":
        return frappe.session.user
    else:
        return None

    # A mobile token authenticates only this API request. Creating a full
    # LoginManager session here updates User.last_login/last_active and commits
    # in the middle of scanner transactions, causing contention on tabUser.
    request_user = frappe.session.user
    if user == request_user:
        return user
    frappe.set_user(user)
    request = getattr(frappe.local, "request", None)
    after_response = getattr(request, "after_response", None) if request else None
    if after_response is not None:
        # Frappe schedules Session.update after the endpoint returns. Restore
        # Guest first so token-only requests cannot update User.last_active.
        after_response.add(lambda: frappe.set_user(request_user))
    return user


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


def _get_row_valuation_context(
    item_code, warehouse, posting_date, posting_time, location=None
):
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
                current_valuation_rate = _safe_float(balance[1])
            else:
                current_valuation_rate = 0.0

            if location:
                current_qty = get_dimension_stock_balance(
                    item_code,
                    warehouse,
                    {"location": location},
                    posting_date=posting_date,
                    posting_time=posting_time,
                )
            elif isinstance(balance, (list, tuple)):
                current_qty = _safe_float(balance[0])
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
        (row.get("location") or "").strip(),
    )

    row.item_name = item_defaults["item_name"]
    row.item_group = item_defaults["item_group"]
    row.stock_uom = item_defaults["stock_uom"]
    row.current_qty = current_qty
    row.current_valuation_rate = current_valuation_rate
    row.current_amount = current_qty * current_valuation_rate

    if doc.get("custom_physical_count"):
        # Blind Physical Count adjusts quantity only. Never create a valuation
        # variance merely because an older warehouse-wide rate was retained.
        valuation_rate = current_valuation_rate or _safe_float(item_defaults["item_valuation_rate"])
    else:
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
        existing.custom_scanned_by = _merge_device_names(
            existing.get("custom_scanned_by"),
            row.get("custom_scanned_by"),
        )

    doc.items = []
    for row in ordered_rows:
        doc.append("items", row.as_dict())


def _canonical_increment_request(reconciliation_id, submission_id, entries):
    payload = {
        "reconciliation_id": reconciliation_id,
        "operation": "increment",
        "submission_id": submission_id,
        "entries": entries,
    }
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return serialized, hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _parse_positive_delta(value, row_number):
    if isinstance(value, bool):
        frappe.throw(f"Entry #{row_number}: quantity must be a finite number greater than zero.")
    try:
        quantity = float(value)
    except (TypeError, ValueError):
        frappe.throw(f"Entry #{row_number}: quantity must be a finite number greater than zero.")
    if not math.isfinite(quantity) or quantity <= 0:
        frappe.throw(f"Entry #{row_number}: quantity must be a finite number greater than zero.")
    return quantity


def _resolve_increment_uom(request_uom, stock_uom, row_number):
    """Always use the item's authoritative ERP Stock UOM for scanner counts."""
    stock_uom = str(stock_uom or "").strip()
    if not stock_uom:
        frappe.throw(
            f"Entry #{row_number}: Item Stock UOM is not configured in ERPNext."
        )
    return stock_uom


def _normalize_submission_id(submission_id):
    try:
        return str(uuid.UUID(str(submission_id or "").strip()))
    except (ValueError, AttributeError, TypeError):
        frappe.throw("submission_id must be a valid UUID for operation='increment'.")


def _lock_reconciliation(reconciliation_id):
    rows = frappe.db.sql(
        "select name from `tabStock Reconciliation` where name = %s for update",
        (reconciliation_id,),
        as_dict=True,
    )
    if not rows:
        raise frappe.DoesNotExistError(f"Stock Reconciliation {reconciliation_id} not found")


def _get_increment_replay(submission_id, request_hash):
    record = frappe.db.get_value(
        "Physical Count Submission",
        submission_id,
        ["request_hash", "result_json", "status"],
        as_dict=True,
    )
    if not record:
        return None
    if record.request_hash != request_hash:
        frappe.throw(
            "submission_id was already used with different request content. "
            "Generate a new UUID for a new submission. "
            "[SUBMISSION_ID_PAYLOAD_MISMATCH]"
        )

    # RECEIVED/QUEUED/VALIDATING records are staging inbox records, not completed
    # replays. Only a finished submission may short-circuit business processing.
    if str(record.status or "").strip().upper() not in {"SUCCESS", "COMPLETED"}:
        return None

    result = json.loads(record.result_json or "{}")
    if not result:
        return None
    result["duplicate_submission"] = True
    return result


def _canonical_request(reconciliation_id, operation, submission_id, entries):
    payload = {
        "reconciliation_id": reconciliation_id,
        "operation": operation,
        "submission_id": submission_id,
        "entries": entries,
    }
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return serialized, hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _parse_finite_number(value, fieldname, row_number):
    if isinstance(value, bool):
        frappe.throw(f"Entry #{row_number}: {fieldname} must be a finite number.")
    try:
        number = float(value)
    except (TypeError, ValueError):
        frappe.throw(f"Entry #{row_number}: {fieldname} must be a finite number.")
    if not math.isfinite(number):
        frappe.throw(f"Entry #{row_number}: {fieldname} must be a finite number.")
    return number


def _audit_timestamp(value):
    if not value:
        return now_datetime()
    text = str(value).strip()
    try:
        if re.fullmatch(r"\d{1,2}:\d{2}:\d{2}\s*[APap][Mm]", text):
            return get_datetime(f"{nowdate()} {text}")
        return get_datetime(text)
    except Exception:
        return now_datetime()


def _validate_adjustment_entry(entry, row_number, doc):
    if not isinstance(entry, dict):
        frappe.throw(f"Entry #{row_number}: each entry must be an object.")
    item_code = str(entry.get("itemCode") or entry.get("item_code") or "").strip()
    item = frappe.db.get_value(
        "Item", {"name": item_code, "disabled": 0}, ["item_name", "stock_uom"], as_dict=True
    )
    if not item:
        frappe.throw(f"Entry #{row_number}: Item '{item_code}' does not exist or is disabled.")

    bin_data = entry.get("bin") or {}
    if not isinstance(bin_data, dict):
        frappe.throw(f"Entry #{row_number}: bin must be an object.")
    submitted_warehouse = str(
        entry.get("warehouse") or bin_data.get("warehouse") or doc.set_warehouse or ""
    ).strip()
    reconciliation_warehouse = (doc.set_warehouse or "").strip()
    if not frappe.db.exists("Warehouse", submitted_warehouse):
        frappe.throw(f"Entry #{row_number}: Warehouse '{submitted_warehouse}' does not exist.")
    if submitted_warehouse != reconciliation_warehouse:
        frappe.throw(
            f"Entry #{row_number}: Warehouse '{submitted_warehouse}' does not match reconciliation "
            f"warehouse '{reconciliation_warehouse}'."
        )
    warehouse = reconciliation_warehouse
    if frappe.db.get_value("Warehouse", warehouse, "company") != doc.company:
        frappe.throw(f"Entry #{row_number}: Warehouse '{warehouse}' does not belong to {doc.company}.")

    location = _resolve_storage_location(entry)
    if not location:
        frappe.throw(f"Entry #{row_number}: Inventory Location is required.")
    _validate_storage_location_warehouse(location, warehouse, row_number)
    expected = _parse_finite_number(
        entry.get("expectedPreviousCount", entry.get("expected_previous_count")),
        "expectedPreviousCount", row_number,
    )
    erp_baseline_raw = entry.get("expectedERPQuantity", entry.get("expected_erp_quantity"))
    erp_baseline = (
        _parse_finite_number(erp_baseline_raw, "expectedERPQuantity", row_number)
        if erp_baseline_raw is not None else None
    )
    quantity_raw = entry.get("quantity")
    physical_count_raw = entry.get("physicalCount", entry.get("physical_count"))
    if physical_count_raw is None:
        physical_count_raw = quantity_raw
    physical_count = _parse_finite_number(
        physical_count_raw, "physicalCount", row_number
    )
    if physical_count < 0:
        frappe.throw(f"Entry #{row_number}: physicalCount cannot be negative.")
    if quantity_raw is not None:
        final_quantity = _parse_finite_number(quantity_raw, "quantity", row_number)
        if final_quantity < 0:
            frappe.throw(f"Entry #{row_number}: quantity cannot be negative.")
        if not _quantities_equal(final_quantity, physical_count):
            frappe.throw(
                f"Entry #{row_number}: quantity and physicalCount must contain the same "
                "final counted quantity."
            )
    transactions = entry.get("transactions") or []
    if not isinstance(transactions, list):
        frappe.throw(f"Entry #{row_number}: transactions must be a list.")

    transaction_ids = set()
    transaction_delta = 0.0
    for transaction_number, transaction in enumerate(transactions, start=1):
        if not isinstance(transaction, dict):
            frappe.throw(
                f"Entry #{row_number} transaction #{transaction_number}: must be an object."
            )
        transaction_id = str(
            transaction.get("id") or transaction.get("transaction_id") or ""
        ).strip()
        if not transaction_id:
            frappe.throw(
                f"Entry #{row_number} transaction #{transaction_number}: id is required."
            )
        if transaction_id in transaction_ids:
            frappe.throw(f"Entry #{row_number}: duplicate transaction ID '{transaction_id}'.")
        transaction_ids.add(transaction_id)
        action = str(transaction.get("action") or "").strip().upper()
        if action not in {"ADD", "DEDUCT"}:
            frappe.throw(
                f"Entry #{row_number} transaction #{transaction_number}: action must be ADD or DEDUCT."
            )
        change = _parse_finite_number(
            transaction.get("quantityChange", transaction.get("quantity_change")),
            "quantityChange", row_number,
        )
        if action == "ADD" and change <= 0:
            frappe.throw(f"Entry #{row_number}: ADD quantityChange must be positive.")
        if action == "DEDUCT" and change >= 0:
            frappe.throw(f"Entry #{row_number}: DEDUCT quantityChange must be negative.")
        running = _parse_finite_number(
            transaction.get("runningQuantity", transaction.get("running_quantity")),
            "runningQuantity", row_number,
        )
        if running < 0:
            frappe.throw(f"Entry #{row_number}: runningQuantity cannot be negative.")
        transaction_delta += change
    quantity_delta_raw = entry.get("quantityDelta", entry.get("quantity_delta"))
    if quantity_delta_raw is None:
        quantity_delta = sum(
            _parse_finite_number(
                transaction.get("quantityChange", transaction.get("quantity_change")),
                "quantityChange", row_number,
            )
            for transaction in transactions
        )
    else:
        quantity_delta = _parse_finite_number(quantity_delta_raw, "quantityDelta", row_number)
    if transactions and not _quantities_equal(quantity_delta, transaction_delta):
        frappe.throw(
            f"Entry #{row_number}: quantityDelta does not match the transaction history."
        )
    stock_uom = _resolve_increment_uom(entry.get("uom"), item.stock_uom, row_number)
    batch_no = str(entry.get("batch_no") or entry.get("batchNo") or "").strip()
    serial_no = str(entry.get("serial_no") or entry.get("serialNo") or "").strip()
    if batch_no and not frappe.db.exists("Batch", {"name": batch_no, "item": item_code}):
        frappe.throw(f"Entry #{row_number}: Batch '{batch_no}' is invalid for {item_code}.")
    item_flags = frappe.db.get_value("Item", item_code, ["has_batch_no", "has_serial_no"], as_dict=True)
    if item_flags.has_batch_no and not batch_no:
        frappe.throw(f"Entry #{row_number}: Batch is required for {item_code}.")
    if item_flags.has_serial_no and not serial_no:
        frappe.throw(f"Entry #{row_number}: Serial numbers are required for {item_code}.")
    return frappe._dict(
        item_code=item_code, item_name=item.item_name or item_code, warehouse=warehouse,
        location=location.name, stock_uom=stock_uom, expected=expected,
        physical_count=physical_count, erp_baseline=erp_baseline,
        quantity_delta=quantity_delta,
        device_id=str(entry.get("deviceId") or "").strip(),
        transactions=transactions, batch_no=batch_no, serial_no=serial_no,
    )


def _make_pcount_stock_entry(doc, purpose, rows, reconciliation_id):
    stock_entry = frappe.new_doc("Stock Entry")
    stock_entry.company = doc.company
    stock_entry.stock_entry_type = purpose
    stock_entry.purpose = purpose
    if stock_entry.meta.has_field("custom_wh_code"):
        stock_entry.custom_wh_code = (
            frappe.db.get_value("Warehouse", rows[0][0].warehouse, "custom_wh_code")
            or "PCOUNT"
        )
    if stock_entry.meta.has_field("custom_reference_document"):
        stock_entry.custom_reference_document = reconciliation_id
    stock_entry.remarks = f"Physical Count variance adjustment for {reconciliation_id}"
    for entry, variance in rows:
        values = {
            "item_code": entry.item_code,
            "qty": abs(variance),
            "uom": entry.stock_uom,
            "stock_uom": entry.stock_uom,
            "conversion_factor": 1,
            "batch_no": entry.batch_no,
            "serial_no": entry.serial_no,
        }
        valuation_rate = _safe_float(frappe.db.get_value("Item", entry.item_code, "valuation_rate"))
        if valuation_rate:
            values["basic_rate"] = valuation_rate
            values["set_basic_rate_manually"] = 1
        else:
            values["allow_zero_valuation_rate"] = 1
        # Physical locations are maintained by Warehouse Allocation, Location
        # Transfer, and the submitted count variance. The Stock Entry adjusts only
        # the ERP warehouse total so the same variance is not counted twice.
        if purpose == "Material Receipt":
            values.update({"t_warehouse": entry.warehouse})
        else:
            values.update({"s_warehouse": entry.warehouse})
        stock_entry.append("items", values)
    stock_entry.insert(ignore_permissions=True)
    stock_entry.submit()
    return stock_entry


def _inventory_tag(transaction):
    """Return a scan transaction's optional Inventory Tag."""
    return normalize_inventory_tag(
        transaction.get("inventoryTag") or transaction.get("inventory_tag") or ""
    )


def _apply_inventory_tag_to_audit_values(values, transaction):
    """Persist a scan transaction's Inventory Tag on its audit record."""
    inventory_tag = _inventory_tag(transaction)
    if not inventory_tag:
        return values
    values["inventory_tag"] = inventory_tag
    return values


def _group_entry_transactions(entry):
    """Group only this request's new transactions by normalized Inventory Tag."""
    groups = {}
    for transaction in entry.transactions or []:
        inventory_tag = _inventory_tag(transaction)
        group = groups.setdefault(inventory_tag, frappe._dict(
            inventory_tag=inventory_tag, transactions=[], quantity_delta=0.0,
        ))
        normalized = dict(transaction)
        normalized.pop("inventory_tag", None)
        if inventory_tag:
            normalized["inventoryTag"] = inventory_tag
        else:
            normalized.pop("inventoryTag", None)
        change = _safe_float(
            transaction.get("quantityChange", transaction.get("quantity_change"))
        )
        normalized["quantityChange"] = change
        group.transactions.append(normalized)
        group.quantity_delta += change
    if not groups:
        return [frappe._dict(
            inventory_tag="", transactions=[], quantity_delta=_safe_float(entry.quantity_delta),
        )]
    return list(groups.values())


def _submit_adjustment_entries(reconciliation_id, submission_id, entries, user):
    savepoint = "physical_count_adjustment"
    frappe.db.savepoint(savepoint)
    try:
        if not isinstance(entries, list) or not entries:
            frappe.throw("At least one adjustment entry is required.")
        _lock_reconciliation(reconciliation_id)
        submission_id = _normalize_submission_id(submission_id)
        request_json, request_hash = _canonical_request(
            reconciliation_id, "adjustment", submission_id, entries
        )
        replay = _get_increment_replay(submission_id, request_hash)
        if replay:
            frappe.db.commit()
            return replay

        doc = frappe.get_doc("Stock Reconciliation", reconciliation_id)
        # Dedicated scanner authorization is the authenticated mobile user plus
        # Role Profile Warehouse Access with Allow Transact. Scanner operators
        # do not require Desk-level Stock Reconciliation write permission.
        ensure_scanner_warehouse_access(user, [doc.set_warehouse], require_transact=True)
        _ensure_pcount_open_for_scanning(doc)
        normalized = [
            _validate_adjustment_entry(entry, index, doc)
            for index, entry in enumerate(entries, start=1)
        ]
        latest_rows = latest_physical_count_groups(
            doc.get("custom_physical_count_results") or []
        )

        planned = []
        for index, entry in enumerate(normalized, start=1):
            location_prefix = physical_count_group_key(frappe._dict(
                item_code=entry.item_code, warehouse=entry.warehouse,
                location=entry.location, batch_no=entry.batch_no,
                serial_no=entry.serial_no, uom=entry.stock_uom,
            ))[:6]
            location_rows = [
                row for key, row in latest_rows.items() if key[:6] == location_prefix
            ]
            live_quantity = _current_inventory_quantity(
                entry.item_code, entry.warehouse, entry.location,
                entry.batch_no, entry.serial_no,
            )
            current = (
                _safe_float(location_rows[0].erp_quantity_before)
                if location_rows else live_quantity
            )
            expected_baseline = (
                entry.erp_baseline
                if entry.erp_baseline is not None
                else current if location_rows else entry.expected
            )
            if not _quantities_equal(live_quantity, expected_baseline):
                entry.expected = expected_baseline
                raise PhysicalCountConflict(live_quantity, entry)

            planned_groups = []
            for group in _group_entry_transactions(entry):
                identity = frappe._dict(
                    item_code=entry.item_code, warehouse=entry.warehouse,
                    location=entry.location, batch_no=entry.batch_no,
                    serial_no=entry.serial_no, uom=entry.stock_uom,
                    inventory_tag=group.inventory_tag,
                )
                key = physical_count_group_key(identity)
                existing = latest_rows.get(key)
                previous = _safe_float(existing.physical_count if existing else 0)
                running = previous
                for transaction in group.transactions:
                    transaction_id = str(
                        transaction.get("id") or transaction.get("transaction_id") or ""
                    ).strip()
                    if frappe.db.exists(
                        "Physical Count Scan Transaction", {"transaction_id": transaction_id}
                    ):
                        frappe.throw(f"Transaction ID '{transaction_id}' has already been submitted.")
                    running += _safe_float(transaction.get("quantityChange"))
                    if running < -1e-9:
                        frappe.throw(
                            f"Entry #{index}: the Inventory Tag group cannot become negative."
                        )
                    transaction["runningQuantity"] = running
                authoritative = previous + group.quantity_delta
                if authoritative < -1e-9:
                    frappe.throw(
                        f"Entry #{index}: the Inventory Tag group cannot become negative."
                    )
                group.previous_physical_count = previous
                group.physical_count = authoritative
                group.existing = existing
                planned_groups.append(group)
                latest_rows[key] = existing or identity
                latest_rows[key].physical_count = authoritative

            location_total = sum(
                _safe_float(row.physical_count)
                for key, row in latest_rows.items()
                if key[:6] == location_prefix
            )
            entry.physical_count = location_total
            planned.append((index, entry, current, planned_groups))

        scanner_full_name = frappe.get_cached_value("User", user, "full_name") or user
        response_entries = []
        audit_docs = []
        submitted_at = now_datetime()
        for index, entry, current, groups in planned:
            variance = entry.physical_count - current
            adjustment = None
            status = "Pending adjustment"
            response_entries.append({
                "item_code": entry.item_code, "warehouse": entry.warehouse,
                "inventory_location": entry.location, "erp_quantity_before": current,
                "physical_count": entry.physical_count, "variance": variance,
                "adjustment_document": adjustment.name if adjustment else "",
                "status": status,
            })
            for tx_index, transaction in enumerate(entry.transactions, start=1):
                transaction_id = str(transaction.get("id") or transaction.get("transaction_id") or "").strip()
                if not transaction_id:
                    frappe.throw(f"Entry #{index} transaction #{tx_index}: id is required.")
                action = str(transaction.get("action") or "").strip().upper()
                if action not in {"ADD", "DEDUCT"}:
                    frappe.throw(f"Entry #{index} transaction #{tx_index}: action must be ADD or DEDUCT.")
                change = _parse_finite_number(
                    transaction.get("quantityChange", transaction.get("quantity_change")),
                    "quantityChange", index,
                )
                audit_values = {
                    "transaction_id": transaction_id, "submission_id": submission_id,
                    "entry_number": index, "reconciliation": reconciliation_id,
                    "item_code": entry.item_code, "warehouse": entry.warehouse,
                    "storage_location": entry.location, "uom": entry.stock_uom, "action": action,
                    "quantity_change": change,
                    "previous_quantity": _safe_float(transaction.get("runningQuantity", transaction.get("running_quantity"))) - change,
                    "running_quantity": _safe_float(transaction.get("runningQuantity", transaction.get("running_quantity"))),
                    "scanned_at": _audit_timestamp(transaction.get("timestamp")),
                    "processed_at": now_datetime(), "scanner_user": user,
                    "scanner_full_name": str(transaction.get("employeeName") or scanner_full_name),
                    "employee_id": str(transaction.get("employeeId") or ""),
                    "device_id": str(transaction.get("deviceId") or entry.device_id),
                }
                audit_docs.append(_apply_inventory_tag_to_audit_values(audit_values, transaction))
            for group_index, group in enumerate(groups, start=1):
                group_variance = group.physical_count - current
                audit_docs.append(_apply_inventory_tag_to_audit_values({
                    "transaction_id": f"{submission_id}:summary:{index}:{group_index}",
                    "submission_id": submission_id, "entry_number": index,
                    "reconciliation": reconciliation_id, "item_code": entry.item_code,
                    "warehouse": entry.warehouse, "storage_location": entry.location,
                    "uom": entry.stock_uom,
                    "action": "SUBMITTED" if group_variance >= 0 else "CORRECTION_SUBMITTED",
                    "quantity_change": group.quantity_delta,
                    "previous_quantity": group.previous_physical_count,
                    "running_quantity": group.physical_count, "scanned_at": now_datetime(),
                    "processed_at": now_datetime(), "scanner_user": user,
                    "scanner_full_name": scanner_full_name, "device_id": entry.device_id,
                    "physical_count": group.physical_count, "variance": group_variance,
                    "adjustment_document_type": "", "adjustment_document": "",
                }, {"inventoryTag": group.inventory_tag}))

                first_transaction = group.transactions[0] if group.transactions else {}
                employee_id = str(first_transaction.get("employeeId") or "").strip()
                employee = employee_id if employee_id and frappe.db.exists("Employee", employee_id) else None
                existing_history = []
                if group.existing and group.existing.scan_history_json:
                    try:
                        parsed_history = json.loads(group.existing.scan_history_json)
                        existing_history = parsed_history if isinstance(parsed_history, list) else []
                    except (TypeError, ValueError):
                        existing_history = []
                history = existing_history + group.transactions
                values = {
                "submission_id": submission_id,
                "inventory_tag": group.inventory_tag,
                "item_code": entry.item_code,
                "item_name": entry.item_name,
                "warehouse": entry.warehouse,
                "inventory_location": entry.location,
                "inventory_location_id": entry.location,
                "location": entry.location,
                "location_name": frappe.db.get_value(
                    "Storage Location", entry.location, "location_name"
                ) or entry.location,
                "uom": entry.stock_uom,
                "batch_no": entry.batch_no,
                "serial_no": entry.serial_no,
                "erp_quantity_before": current,
                "expected_previous_count": group.previous_physical_count,
                "quantity_delta": group.quantity_delta,
                "physical_count": group.physical_count,
                "variance": group_variance,
                "adjustment_document_type": "",
                "adjustment_document": "",
                "adjustment_status": "Pending",
                "scanner_user": user,
                "scanner_full_name": scanner_full_name,
                "employee": employee,
                "device_id": entry.device_id,
                "counted_at": (
                    _audit_timestamp(first_transaction.get("timestamp"))
                    if first_transaction else submitted_at
                ),
                "submitted_at": submitted_at,
                "transaction_count": len(history),
                "scan_history_json": json.dumps(history, sort_keys=True, default=str),
                "status": status,
                }
                if group.existing:
                    for fieldname, value in values.items():
                        group.existing.set(fieldname, value)
                else:
                    doc.append("custom_physical_count_results", values)

        doc.save(ignore_permissions=True)
        for values in audit_docs:
            frappe.get_doc({"doctype": "Physical Count Scan Transaction", **values}).insert(ignore_permissions=True)
        result = {
            "success": True, "item_count": len(response_entries), "submission_id": submission_id,
            "duplicate_submission": False, "reconciliation_id": reconciliation_id,
            "docstatus": doc.docstatus, "status": "Draft",
            "message": "Physical Count saved to Draft Stock Reconciliation.",
            "results": response_entries,
        }
        submission_values = {
            "reconciliation": reconciliation_id,
            "operation": "adjustment",
            "status": "COMPLETED",
            "device_ids": ", ".join(sorted({entry.device_id for entry in normalized if entry.device_id})),
            "processed_at": now_datetime(),
            "processed_by": user,
            "request_hash": request_hash,
            "request_json": request_json,
            "result_json": json.dumps(result, sort_keys=True, separators=(",", ":")),
            "error_code": "",
            "error_message": "",
        }
        if frappe.db.exists("Physical Count Submission", submission_id):
            submission = frappe.get_doc("Physical Count Submission", submission_id)
            for fieldname, value in submission_values.items():
                submission.set(fieldname, value)
            submission.save(ignore_permissions=True)
        else:
            frappe.get_doc({
                "doctype": "Physical Count Submission",
                "submission_id": submission_id,
                **submission_values,
            }).insert(ignore_permissions=True)
        frappe.db.commit()
        return result
    except Exception:
        frappe.db.rollback(save_point=savepoint)
        raise


def post_pending_pcount_adjustments(doc):
    """Post the latest location counts when a Physical Count is activated."""
    unallocated_cache = {}
    aggregates = aggregate_physical_count_locations(
        doc.get("custom_physical_count_results") or [], _effective_physical_count
    )
    if not aggregates:
        frappe.throw("No Physical Count Details are available to activate.")

    planned = []
    for aggregate in aggregates.values():
        result = aggregate.groups[0]
        location = result.get("location") or result.inventory_location
        if str(result.submission_id or "").startswith("AUTO-UNALLOCATED-"):
            if result.warehouse not in unallocated_cache:
                unallocated_cache[result.warehouse] = {
                    row.item_code: _safe_float(row.quantity)
                    for row in _get_unallocated_warehouse_balances(result.warehouse)
                }
            current = unallocated_cache[result.warehouse].get(result.item_code, 0)
        else:
            current = _current_inventory_quantity(
                result.item_code, result.warehouse, location,
                result.get("batch_no"), result.get("serial_no"),
            )
        if not _quantities_equal(current, aggregate.erp_quantity_before):
            frappe.throw(
                "ERP stock changed after this physical count was recorded for "
                f"{result.item_code} at {location}. Expected "
                f"{aggregate.erp_quantity_before}, found {current}. Refresh and review."
            )
        variance = aggregate.effective_count - current
        entry = frappe._dict(
            item_code=result.item_code,
            warehouse=result.warehouse,
            location=location,
            stock_uom=result.uom,
            batch_no=result.get("batch_no") or "",
            serial_no=result.get("serial_no") or "",
        )
        planned.append((aggregate, entry, current, variance))

    receipt_rows = [(entry, variance) for _, entry, _, variance in planned if variance > 1e-9]
    issue_rows = [(entry, variance) for _, entry, _, variance in planned if variance < -1e-9]
    receipt = _make_pcount_stock_entry(doc, "Material Receipt", receipt_rows, doc.name) if receipt_rows else None
    issue = _make_pcount_stock_entry(doc, "Material Issue", issue_rows, doc.name) if issue_rows else None

    for aggregate, entry, current, variance in planned:
        adjustment = receipt if variance > 1e-9 else issue if variance < -1e-9 else None
        for result in aggregate.groups:
            result.erp_quantity_before = current
            result.adjustment_document_type = "Stock Entry" if adjustment else ""
            result.adjustment_document = adjustment.name if adjustment else ""
            result.adjustment_status = "Submitted" if adjustment else "Not required"
            result.status = "Adjusted" if adjustment else "No adjustment required"

            filters = {
                "submission_id": result.submission_id,
                "item_code": result.item_code,
                "warehouse": result.warehouse,
                "storage_location": entry.location,
                "physical_count": ["is", "set"],
            }
            if result.get("inventory_tag"):
                filters["inventory_tag"] = result.inventory_tag
            summary_transaction = frappe.db.get_value(
                "Physical Count Scan Transaction", filters, "name"
            )
            if summary_transaction:
                frappe.db.set_value(
                    "Physical Count Scan Transaction", summary_transaction,
                    {
                        "variance": variance,
                        "adjustment_document_type": "Stock Entry" if adjustment else "",
                        "adjustment_document": adjustment.name if adjustment else "",
                    },
                    update_modified=False,
                )

    return [document.name for document in (receipt, issue) if document]


@frappe.whitelist()
def refresh_pcount_summary(reconciliation_id):
    """Rebuild the read-only Item + Warehouse summary for a Physical Count."""
    doc = frappe.get_doc("Stock Reconciliation", reconciliation_id)
    doc.check_permission("write")
    if not doc.get("custom_physical_count"):
        frappe.throw("Physical Count is not enabled for this Stock Reconciliation.")
    if doc.docstatus != 0:
        frappe.throw("Only a Draft Physical Count can be refreshed.")
    doc.save(ignore_permissions=True)
    return {
        "success": True,
        "reconciliation_id": doc.name,
        "summary_rows": len(doc.items),
    }


def _validate_increment_entry(entry, row_number, doc):
    if not isinstance(entry, dict):
        frappe.throw(f"Entry #{row_number}: each entry must be an object.")

    item_code = str(entry.get("itemCode") or "").strip()
    if not item_code or not frappe.db.exists("Item", {"name": item_code, "disabled": 0}):
        frappe.throw(f"Entry #{row_number}: Item '{item_code}' does not exist or is disabled.")

    quantity = _parse_positive_delta(entry.get("quantity"), row_number)
    bin_data = entry.get("bin") or {}
    if not isinstance(bin_data, dict):
        frappe.throw(f"Entry #{row_number}: bin must be an object.")

    submitted_warehouse = str(bin_data.get("warehouse") or "").strip()
    reconciliation_warehouse = (doc.set_warehouse or "").strip()
    warehouse = reconciliation_warehouse
    if submitted_warehouse and (
        _warehouse_identity(submitted_warehouse)
        != _warehouse_identity(reconciliation_warehouse)
    ):
        warehouse = _resolve_warehouse(submitted_warehouse)
    if submitted_warehouse and not warehouse:
        frappe.throw(f"Entry #{row_number}: Warehouse '{submitted_warehouse}' does not exist.")
    if not warehouse:
        frappe.throw(f"Entry #{row_number}: Default Warehouse is required on the reconciliation.")
    if warehouse != reconciliation_warehouse:
        frappe.throw(
            f"Entry #{row_number}: Warehouse '{warehouse}' does not match reconciliation "
            f"warehouse '{doc.set_warehouse}'."
        )
    if frappe.db.get_value("Warehouse", warehouse, "company") != doc.company:
        frappe.throw(f"Entry #{row_number}: Warehouse '{warehouse}' does not belong to {doc.company}.")

    location = _resolve_storage_location(entry)
    if not location:
        frappe.throw(f"Entry #{row_number}: Storage Location is required.")
    _validate_storage_location_warehouse(location, warehouse, row_number)

    stock_uom = frappe.db.get_value("Item", item_code, "stock_uom")
    stock_uom = _resolve_increment_uom(entry.get("uom"), stock_uom, row_number)
    item_name = frappe.db.get_value("Item", item_code, "item_name") or item_code

    device_id = str(entry.get("deviceId") or "").strip()
    if not device_id:
        frappe.throw(f"Entry #{row_number}: deviceId is required.")

    action = str(
        entry.get("action")
        or entry.get("scanMode")
        or entry.get("scan_mode")
        or "ADD"
    ).strip().upper()
    if action not in {"ADD", "DEDUCT"}:
        frappe.throw(f"Entry #{row_number}: action must be ADD or DEDUCT.")

    return frappe._dict(
        item_code=item_code,
        item_name=item_name,
        warehouse=warehouse,
        location=location.name,
        stock_uom=stock_uom,
        quantity=quantity,
        device_id=device_id,
        action=action,
        scanned_at=entry.get("timestamp") or entry.get("scannedAt") or entry.get("scanned_at"),
        inventory_tag=_inventory_tag(entry),
    )


def _submit_increment_entries(reconciliation_id, submission_id, entries, user):
    savepoint = "physical_count_increment"
    frappe.db.savepoint(savepoint)
    try:
        if not isinstance(entries, list):
            frappe.throw("Entries must be a list for operation='increment'.")
        _lock_reconciliation(reconciliation_id)
        submission_id = _normalize_submission_id(submission_id)
        request_json, request_hash = _canonical_increment_request(
            reconciliation_id, submission_id, entries
        )

        replay = _get_increment_replay(submission_id, request_hash)
        if replay:
            frappe.db.commit()
            return replay

        doc = frappe.get_doc("Stock Reconciliation", reconciliation_id)
        # Keep scanner authorization consistent with adjustment submissions.
        ensure_scanner_warehouse_access(user, [doc.set_warehouse], require_transact=True)
        _ensure_pcount_open_for_scanning(doc)
        if not doc.set_warehouse:
            frappe.throw("Default Warehouse is required on the Stock Reconciliation.")

        normalized = [
            _validate_increment_entry(entry, index, doc)
            for index, entry in enumerate(entries, start=1)
        ]
        if not normalized:
            frappe.throw("At least one increment entry is required.")

        existing_rows = defaultdict(list)
        for row in doc.items:
            identity = (
                (row.item_code or "").strip(),
                (row.warehouse or "").strip(),
                (row.get("location") or "").strip(),
                (row.get("stock_uom") or "").strip(),
            )
            existing_rows[identity].append(row)

        scanner_full_name = frappe.get_cached_value("User", user, "full_name") or user
        updated_entries = []
        scan_transactions = []
        for entry_number, increment in enumerate(normalized, start=1):
            identity = (
                increment.item_code.strip(),
                increment.warehouse.strip(),
                increment.location.strip(),
                increment.stock_uom.strip(),
            )
            matches = existing_rows.get(identity, [])
            if len(matches) > 1:
                frappe.throw(
                    "Multiple ERP rows already exist for increment identity "
                    f"{identity}; consolidate them before incrementing."
                )

            if matches:
                row = matches[0]
                previous_quantity = _safe_float(row.qty)
            else:
                row = doc.append("items", {})
                row.item_code = increment.item_code
                row.warehouse = increment.warehouse
                row.location = increment.location
                row.stock_uom = increment.stock_uom
                previous_quantity = 0.0
                existing_rows[identity].append(row)

            scan_quantity = _safe_float(increment.quantity)
            quantity_change = scan_quantity if increment.action == "ADD" else -scan_quantity
            total_quantity = previous_quantity + quantity_change
            if total_quantity < 0:
                frappe.throw(
                    f"Entry #{entry_number}: Cannot deduct {scan_quantity:g} from "
                    f"{increment.item_code} at {increment.location}; current quantity is "
                    f"{previous_quantity:g}. Quantity was not changed."
                )
            row.qty = total_quantity
            row.custom_scanned_device = _merge_device_names(
                row.get("custom_scanned_device"), increment.device_id
            )
            row.custom_scanned_by = _merge_device_names(
                row.get("custom_scanned_by"), scanner_full_name
            )
            _apply_item_fields(row, doc)
            updated_entries.append(
                {
                    "item_code": increment.item_code,
                    "item_name": increment.item_name,
                    "warehouse": increment.warehouse,
                    "storage_location": increment.location,
                    "uom": increment.stock_uom,
                    "action": increment.action,
                    "previous_quantity": previous_quantity,
                    "quantity_change": quantity_change,
                    "added_quantity": scan_quantity if increment.action == "ADD" else 0,
                    "deducted_quantity": scan_quantity if increment.action == "DEDUCT" else 0,
                    "total_quantity": row.qty,
                }
            )
            scan_transactions.append(
                {
                    "doctype": "Physical Count Scan Transaction",
                    "transaction_id": f"{submission_id}:increment:{entry_number}",
                    "submission_id": submission_id,
                    "entry_number": entry_number,
                    "reconciliation": reconciliation_id,
                    "item_code": increment.item_code,
                    "warehouse": increment.warehouse,
                    "storage_location": increment.location,
                    "uom": increment.stock_uom,
                    "action": increment.action,
                    "quantity_change": quantity_change,
                    "previous_quantity": previous_quantity,
                    "running_quantity": row.qty,
                    "scanned_at": increment.scanned_at or now_datetime(),
                    "processed_at": now_datetime(),
                    "scanner_user": user,
                    "scanner_full_name": scanner_full_name,
                    "device_id": increment.device_id,
                    "inventory_tag": increment.inventory_tag,
                }
            )

        doc.save(ignore_permissions=True)
        for transaction in scan_transactions:
            frappe.get_doc(transaction).insert(ignore_permissions=True)
        result = {
            "success": True,
            "operation": "increment",
            "submission_id": submission_id,
            "duplicate_submission": False,
            "item_count": len(updated_entries),
            "updated_entries": updated_entries,
        }
        device_ids = sorted({entry.device_id for entry in normalized})
        submission = frappe.get_doc(
            {
                "doctype": "Physical Count Submission",
                "submission_id": submission_id,
                "reconciliation": reconciliation_id,
                "device_ids": ", ".join(device_ids),
                "processed_at": now_datetime(),
                "processed_by": user,
                "request_hash": request_hash,
                "request_json": request_json,
                "result_json": json.dumps(result, sort_keys=True, separators=(",", ":")),
            }
        )
        submission.insert(ignore_permissions=True)
        frappe.db.commit()
        return result
    except Exception:
        frappe.db.rollback(save_point=savepoint)
        raise


def _adjustment_validation_context(entries, error):
    if not isinstance(entries, list):
        return {}
    match = re.search(r"(?:Entry|Row)\s+#(\d+)", str(error), flags=re.IGNORECASE)
    if not match:
        return {}
    row_number = int(match.group(1))
    if row_number < 1 or row_number > len(entries):
        return {}
    entry = entries[row_number - 1]
    if not isinstance(entry, dict):
        return {}
    bin_data = entry.get("bin") if isinstance(entry.get("bin"), dict) else {}
    return {
        "item_code": entry.get("itemCode") or entry.get("item_code") or "",
        "inventory_location": (
            entry.get("inventoryLocation")
            or entry.get("inventory_location")
            or entry.get("storageLocation")
            or entry.get("storage_location")
            or bin_data.get("locationId")
            or bin_data.get("location_id")
            or ""
        ),
        "quantity": entry.get("quantity"),
        "quantity_delta": entry.get("quantityDelta", entry.get("quantity_delta")),
        "physical_count": entry.get("physicalCount", entry.get("physical_count")),
    }


def _adjustment_validation_message(error, context):
    if not context:
        return str(error)
    details = ", ".join(f"{field}={context.get(field)}" for field in (
        "item_code", "inventory_location", "quantity", "quantity_delta", "physical_count"
    ))
    return f"{error} [{details}]"


def _find_invalid_submitted_item(entries):
    """Return the first missing/disabled submitted item before document validation."""
    if not isinstance(entries, list):
        return None

    submitted = []
    for row_number, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            continue
        item_code = str(entry.get("itemCode") or entry.get("item_code") or "").strip()
        submitted.append((row_number, item_code))

    item_codes = list({item_code for _, item_code in submitted if item_code})
    enabled_items = set(
        frappe.get_all(
            "Item",
            filters={"name": ["in", item_codes], "disabled": 0},
            pluck="name",
        )
    ) if item_codes else set()
    return next(
        (
            frappe._dict(row_number=row_number, item_code=item_code)
            for row_number, item_code in submitted
            if not item_code or item_code not in enabled_items
        ),
        None,
    )


def _pcount_upload_counts(entries):
    locations = set()
    devices = set()
    transaction_count = 0
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        bin_data = entry.get("bin") if isinstance(entry.get("bin"), dict) else {}
        location = str(
            entry.get("inventoryLocation")
            or entry.get("inventory_location")
            or entry.get("storageLocation")
            or entry.get("storage_location")
            or bin_data.get("locationId")
            or bin_data.get("location_id")
            or ""
        ).strip()
        if location:
            locations.add(location)
        device_id = str(entry.get("deviceId") or "").strip()
        if device_id:
            devices.add(device_id)
        transactions = entry.get("transactions") or []
        if isinstance(transactions, list):
            transaction_count += len(transactions)
    return len(locations), len(entries or []), transaction_count, devices


def _set_pcount_submission_failure(submission_id, status, error_code, message, user=None):
    if not frappe.db.exists("Physical Count Submission", submission_id):
        return
    submission = frappe.get_doc("Physical Count Submission", submission_id)
    submission.status = status
    submission.error_code = error_code
    submission.error_message = str(message or "")[:10000]
    submission.processed_at = now_datetime()
    if user:
        submission.processed_by = user
    submission.save(ignore_permissions=True)
    frappe.db.commit()


def process_pcount_submission(submission_id):
    """Background worker for a durably received Physical Count upload."""
    submission = frappe.get_doc("Physical Count Submission", submission_id)
    if str(submission.status or "").strip().upper() in {"SUCCESS", "COMPLETED"}:
        return json.loads(submission.result_json or "{}")

    payload = json.loads(submission.request_json or "{}")
    entries = payload.get("entries") or []
    reconciliation_id = payload.get("reconciliation_id") or submission.reconciliation
    user = submission.get("received_by") or submission.get("processed_by")
    if not user:
        raise frappe.ValidationError("Physical Count Submission has no receiving user.")

    submission.status = "VALIDATING"
    submission.processing_started_at = now_datetime()
    submission.error_code = ""
    submission.error_message = ""
    submission.save(ignore_permissions=True)
    frappe.db.commit()

    try:
        return _submit_adjustment_entries(
            reconciliation_id,
            submission_id,
            entries,
            user,
        )
    except PhysicalCountConflict as exc:
        context = {
            "success": False,
            "error_code": "PCOUNT_STOCK_CHANGED",
            "message": str(exc),
            "current_erp_quantity": exc.current_quantity,
            "item_code": exc.entry.get("item_code"),
            "warehouse": exc.entry.get("warehouse"),
            "inventory_location": exc.entry.get("location"),
            "expected_previous_count": exc.entry.get("expected"),
            "physical_count": exc.entry.get("physical_count"),
            "submission_id": submission_id,
        }
        _set_pcount_submission_failure(
            submission_id, "NEEDS_REVIEW", "PCOUNT_STOCK_CHANGED",
            json.dumps(context, sort_keys=True, default=str), user,
        )
        return context
    except PhysicalCountNotOpen as exc:
        _set_pcount_submission_failure(
            submission_id, "NEEDS_REVIEW", "PCOUNT_NOT_OPEN", str(exc), user,
        )
        return {"success": False, "error_code": "PCOUNT_NOT_OPEN", "message": str(exc)}
    except (frappe.ValidationError, frappe.DuplicateEntryError) as exc:
        mismatch = "SUBMISSION_ID_PAYLOAD_MISMATCH" in str(exc)
        context = _adjustment_validation_context(entries, exc)
        message = _adjustment_validation_message(exc, context)
        code = "SUBMISSION_ID_PAYLOAD_MISMATCH" if mismatch else "PCOUNT_VALIDATION_ERROR"
        _set_pcount_submission_failure(submission_id, "NEEDS_REVIEW", code, message, user)
        return {"success": False, "error_code": code, "message": message, **context}
    except Exception as exc:
        frappe.log_error(frappe.get_traceback(), "stock_reconciliation.pcount_background")
        _set_pcount_submission_failure(
            submission_id, "FAILED", "PCOUNT_PROCESSING_ERROR", str(exc), user,
        )
        raise


@frappe.whitelist(allow_guest=True)
def upload_pcount_submission(reconciliation_id, entries, submission_id, mobile_token=None):
    """Durably receive one Physical Count payload and process it asynchronously."""
    user = _authenticate_request_user(mobile_token)
    if user == "Guest" or not user:
        frappe.local.response["http_status_code"] = 401
        return {"success": False, "message": "Session expired. Please log in again."}

    if isinstance(entries, str):
        try:
            entries = json.loads(entries)
        except (TypeError, ValueError):
            frappe.local.response["http_status_code"] = 400
            return {"success": False, "message": "Entries must be valid JSON."}
    if not isinstance(entries, list) or not entries:
        frappe.local.response["http_status_code"] = 400
        return {"success": False, "message": "At least one Physical Count entry is required."}

    submission_id = _normalize_submission_id(submission_id)
    request_json, request_hash = _canonical_request(
        reconciliation_id, "adjustment", submission_id, entries
    )

    existing = frappe.db.get_value(
        "Physical Count Submission", submission_id,
        ["request_hash", "status", "result_json", "error_code", "error_message"],
        as_dict=True,
    )
    if existing:
        if existing.request_hash != request_hash:
            frappe.local.response["http_status_code"] = 409
            return {
                "success": False,
                "error_code": "SUBMISSION_ID_PAYLOAD_MISMATCH",
                "message": "submission_id was already used with different request content.",
                "submission_id": submission_id,
            }
        return {
            "success": True,
            "duplicate_submission": True,
            "submission_id": submission_id,
            "status": existing.status,
            "error_code": existing.error_code or "",
            "error_message": existing.error_message or "",
            "result": json.loads(existing.result_json or "{}"),
        }

    # Cheap acceptance checks only. Item/location/UOM/baseline validation stays
    # in the background processor so the scanner is not held open by ERP work.
    doc = frappe.get_doc("Stock Reconciliation", reconciliation_id)
    ensure_scanner_warehouse_access(user, [doc.set_warehouse], require_transact=True)
    _ensure_pcount_open_for_scanning(doc)

    location_count, entry_count, transaction_count, devices = _pcount_upload_counts(entries)
    submission = frappe.get_doc({
        "doctype": "Physical Count Submission",
        "submission_id": submission_id,
        "reconciliation": reconciliation_id,
        "operation": "adjustment",
        "status": "RECEIVED",
        "received_at": now_datetime(),
        "received_by": user,
        "device_ids": ", ".join(sorted(devices)),
        "request_hash": request_hash,
        "request_json": request_json,
        "total_locations": location_count,
        "total_entries": entry_count,
        "total_transactions": transaction_count,
    })
    submission.insert(ignore_permissions=True)
    frappe.db.commit()

    frappe.db.set_value(
        "Physical Count Submission", submission_id, "status", "QUEUED",
        update_modified=False,
    )
    frappe.db.commit()
    frappe.enqueue(
        "qcmc_logic.api.stock_reconciliation.process_pcount_submission",
        submission_id=submission_id,
        queue="long",
        job_name=f"pcount:{submission_id}",
    )

    return {
        "success": True,
        "duplicate_submission": False,
        "submission_id": submission_id,
        "status": "QUEUED",
        "total_locations": location_count,
        "total_entries": entry_count,
        "total_transactions": transaction_count,
    }


@frappe.whitelist(allow_guest=True)
def get_pcount_submission_status(submission_id, mobile_token=None):
    """Return the processing state for one uploaded Physical Count."""
    user = _authenticate_request_user(mobile_token)
    if user == "Guest" or not user:
        frappe.local.response["http_status_code"] = 401
        return {"success": False, "message": "Session expired. Please log in again."}

    submission = frappe.get_doc("Physical Count Submission", submission_id)
    reconciliation = frappe.get_doc("Stock Reconciliation", submission.reconciliation)
    ensure_scanner_warehouse_access(user, [reconciliation.set_warehouse], require_transact=True)
    return {
        "success": True,
        "submission_id": submission.submission_id,
        "reconciliation_id": submission.reconciliation,
        "status": submission.status,
        "received_at": submission.get("received_at"),
        "processing_started_at": submission.get("processing_started_at"),
        "processed_at": submission.get("processed_at"),
        "total_locations": submission.get("total_locations") or 0,
        "total_entries": submission.get("total_entries") or 0,
        "total_transactions": submission.get("total_transactions") or 0,
        "error_code": submission.get("error_code") or "",
        "error_message": submission.get("error_message") or "",
        "result": json.loads(submission.result_json or "{}"),
    }


@frappe.whitelist(allow_guest=True)
def submit_pcount_entries(
    reconciliation_id,
    entries,
    mobile_token=None,
    operation=None,
    submission_id=None,
    action=None,
    scan_mode=None,
):
    """Upsert summarized P. Count scan data without removing other devices' rows."""
    user = _authenticate_request_user(mobile_token)
    if user == "Guest" or not user:
        frappe.local.response["http_status_code"] = 401
        return {"success": False, "message": "Session expired. Please log in again."}

    if isinstance(entries, str):
        try:
            entries = json.loads(entries)
        except (TypeError, ValueError):
            frappe.local.response["http_status_code"] = 400
            return {"success": False, "message": "Entries must be valid JSON."}

    invalid_item = _find_invalid_submitted_item(entries)
    if invalid_item:
        frappe.local.response["http_status_code"] = 400
        item_code = invalid_item.item_code
        return {
            "success": False,
            "error_code": "ITEM_NOT_FOUND",
            "message": (
                f"Item '{item_code}' does not exist or is disabled in ERPNext."
                if item_code else
                f"Submitted row #{invalid_item.row_number} has no item_code."
            ),
            "item_code": item_code,
            "row_number": invalid_item.row_number,
        }

    normalized_operation = str(operation or "").strip().upper()
    request_action = str(action or scan_mode or "").strip().upper()
    if normalized_operation in {"ADD", "DEDUCT"}:
        request_action = normalized_operation
        normalized_operation = "INCREMENT"
    if normalized_operation == "ADJUSTMENT":
        try:
            return _submit_adjustment_entries(reconciliation_id, submission_id, entries, user)
        except PhysicalCountNotOpen as exc:
            frappe.local.response["http_status_code"] = 409
            return {
                "success": False, "error_code": "PCOUNT_NOT_OPEN",
                "message": str(exc), "reconciliation_id": reconciliation_id,
            }
        except PhysicalCountConflict as exc:
            frappe.local.response["http_status_code"] = 409
            return {
                "success": False, "error_code": "PCOUNT_STOCK_CHANGED",
                "message": str(exc), "current_erp_quantity": exc.current_quantity,
                "item_code": exc.entry.get("item_code"), "warehouse": exc.entry.get("warehouse"),
                "inventory_location": exc.entry.get("location"),
                "expected_previous_count": exc.entry.get("expected"),
                "physical_count": exc.entry.get("physical_count"),
                "submission_id": submission_id,
            }
        except frappe.DoesNotExistError:
            frappe.local.response["http_status_code"] = 404
            return {"success": False, "message": f"Stock Reconciliation '{reconciliation_id}' not found."}
        except frappe.PermissionError:
            frappe.local.response["http_status_code"] = 403
            return {"success": False, "message": "You do not have permission to modify this Stock Reconciliation."}
        except (frappe.ValidationError, frappe.DuplicateEntryError) as exc:
            mismatch = "SUBMISSION_ID_PAYLOAD_MISMATCH" in str(exc)
            context = _adjustment_validation_context(entries, exc)
            frappe.local.response["http_status_code"] = 409 if mismatch else 400
            return {
                "success": False,
                "error_code": "SUBMISSION_ID_PAYLOAD_MISMATCH" if mismatch else "PCOUNT_VALIDATION_ERROR",
                "message": _adjustment_validation_message(exc, context),
                "submission_id": submission_id,
                **context,
            }
        except Exception:
            frappe.log_error(frappe.get_traceback(), "stock_reconciliation.adjustment")
            frappe.local.response["http_status_code"] = 500
            return {"success": False, "message": "Failed to save the physical count. No count was recorded."}
    if normalized_operation == "INCREMENT":
        if request_action and isinstance(entries, list):
            if request_action not in {"ADD", "DEDUCT"}:
                frappe.local.response["http_status_code"] = 400
                return {"success": False, "message": "action must be ADD or DEDUCT."}
            entries = [
                {**entry, "action": entry.get("action") or request_action}
                if isinstance(entry, dict) else entry
                for entry in entries
            ]
        try:
            return _submit_increment_entries(reconciliation_id, submission_id, entries, user)
        except PhysicalCountNotOpen as exc:
            frappe.local.response["http_status_code"] = 409
            return {
                "success": False, "operation": "increment",
                "error_code": "PCOUNT_NOT_OPEN", "message": str(exc),
                "reconciliation_id": reconciliation_id,
                "submission_id": submission_id,
            }
        except frappe.DoesNotExistError:
            frappe.local.response["http_status_code"] = 404
            return {
                "success": False,
                "operation": "increment",
                "submission_id": submission_id,
                "message": f"Stock Reconciliation '{reconciliation_id}' not found.",
            }
        except frappe.PermissionError:
            frappe.local.response["http_status_code"] = 403
            return {
                "success": False,
                "operation": "increment",
                "submission_id": submission_id,
                "message": "You do not have permission to modify this Stock Reconciliation.",
            }
        except (frappe.ValidationError, frappe.DuplicateEntryError) as exc:
            frappe.local.response["http_status_code"] = 409 if "submission_id" in str(exc) else 400
            return {
                "success": False,
                "operation": "increment",
                "submission_id": submission_id,
                "message": str(exc),
            }
        except Exception:
            frappe.log_error(frappe.get_traceback(), "stock_reconciliation.increment")
            frappe.local.response["http_status_code"] = 500
            return {
                "success": False,
                "operation": "increment",
                "submission_id": submission_id,
                "message": "Failed to apply increment. No quantities were changed.",
            }
    if normalized_operation:
        frappe.local.response["http_status_code"] = 400
        return {"success": False, "message": f"Unsupported operation '{operation}'."}

    scanner_full_name = frappe.get_cached_value("User", user, "full_name") or user
    try:
        if not reconciliation_id:
            frappe.throw("Reconciliation ID is required")

        if isinstance(entries, str):
            entries = json.loads(entries)

        if not isinstance(entries, list):
            frappe.throw("Entries must be a list")

        doc = frappe.get_doc("Stock Reconciliation", reconciliation_id)

        ensure_scanner_warehouse_access(user, [doc.set_warehouse], require_transact=True)

        if doc.docstatus != 0:
            frappe.local.response["http_status_code"] = 400
            return {
                "success": False,
                "message": f"Stock Reconciliation '{reconciliation_id}' is not in Draft status and cannot be modified",
            }

        if not doc.set_warehouse:
            frappe.local.response["http_status_code"] = 400
            return {
                "success": False,
                "message": "Default Warehouse is required on the Stock Reconciliation before scanning.",
            }

        # Storage Location is part of the row identity. Batch/lot is not.
        grouped = defaultdict(float)
        grouped_devices = defaultdict(set)
        grouped_users = defaultdict(set)
        skipped = []
        duplicate_devices = []

        # Legacy requests carry cumulative totals. Keep that contract, but
        # always record the count directly at the exact scanned location.
        combined_entries = {}
        for entry in entries:
            key = (
                (entry.get("itemCode") or "").strip(),
                (entry.get("deviceId") or "").strip(),
                str(
                    (entry.get("bin") or {}).get("locationId")
                    or (entry.get("bin") or {}).get("location_id")
                    or entry.get("storageLocation")
                    or entry.get("storage_location")
                    or ""
                ).strip(),
            )
            if key not in combined_entries:
                combined_entries[key] = dict(entry)
                combined_entries[key]["quantity"] = 0
            # Preview rows repeat the original scanner total on every
            # allocation. Use the largest reported total rather than summing
            # identical distributed copies (20,000 + 20,000 != 40,000).
            combined_entries[key]["quantity"] = max(
                _safe_float(combined_entries[key]["quantity"]),
                _safe_float(entry.get("quantity")),
            )

        for entry in combined_entries.values():
            item_code = (entry.get("itemCode") or "").strip()
            storage_location = _resolve_storage_location(entry)
            if not storage_location:
                skipped.append(f"{item_code or 'Unknown item'} (Storage Location master QR is required)")
                continue

            device_id = (entry.get("deviceId") or "").strip()
            quantity = _safe_float(entry.get("quantity"))

            if not item_code or quantity <= 0:
                continue

            warehouse = doc.set_warehouse.strip()
            location = storage_location.name.strip()
            stock_uom = frappe.db.get_value("Item", item_code, "stock_uom") or ""
            key = (item_code, warehouse, location, stock_uom.strip())
            grouped[key] += quantity
            if device_id:
                grouped_devices[key].add(device_id)
            grouped_users[key].add(scanner_full_name)

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
        for (item_code, warehouse, location, stock_uom), qty in grouped.items():
            key = (item_code, warehouse, location, stock_uom)
            row = existing_rows.get(key)
            incoming_devices = grouped_devices.get(key, set())
            incoming_users = grouped_users.get(key, set())

            if row:
                existing_devices = {
                    device.strip()
                    for device in (row.get("custom_scanned_device") or "").split(",")
                    if device.strip()
                }
                repeated_devices = existing_devices.intersection(incoming_devices)

                # A scanner sends its accumulated total for this location. When
                # that same scanner submits again, replace its earlier total so
                # corrections update the draft row instead of being ignored.
                # A new scanner still contributes an additional count.
                if repeated_devices and existing_devices.difference(incoming_devices):
                    duplicate_devices.extend(sorted(repeated_devices))
                    continue

                row.qty = qty if repeated_devices else _safe_float(row.qty) + qty
                merged_devices = sorted(existing_devices.union(incoming_devices))
                if merged_devices:
                    row.custom_scanned_device = _merge_device_names(", ".join(merged_devices))
                row.custom_scanned_by = _merge_device_names(
                    row.get("custom_scanned_by"), ", ".join(sorted(incoming_users))
                )
                row.location = location
                _apply_item_fields(row, doc)
                updated += 1
            else:
                row = doc.append("items", {})
                row.item_code = item_code
                row.warehouse = warehouse
                row.qty = qty
                row.location = location
                row.stock_uom = stock_uom
                if incoming_devices:
                    row.custom_scanned_device = _merge_device_names(", ".join(sorted(incoming_devices)))
                row.custom_scanned_by = _merge_device_names(", ".join(sorted(incoming_users)))
                _apply_item_fields(row, doc)
                inserted += 1

        if duplicate_devices:
            frappe.local.response["http_status_code"] = 409
            return {
                "success": False,
                "message": (
                    "This row also contains counts from another scanner, so its quantity cannot be "
                    "safely replaced. Submit each scanner to a separate bin/location row."
                ),
                "duplicate_devices": sorted(set(duplicate_devices)),
            }

        _consolidate_duplicate_location_rows(doc)
        for row in doc.items:
            _apply_item_fields(row, doc)

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


def redistribute_existing_scanner_rows(reconciliation_id):
    """Compatibility endpoint; physical-count rows are no longer redistributed."""
    doc = frappe.get_doc("Stock Reconciliation", reconciliation_id)
    if doc.docstatus != 0:
        frappe.throw("Only draft Stock Reconciliations can be redistributed.")
    return [
        {
            "item_code": row.item_code,
            "warehouse": row.warehouse,
            "location": row.location,
            "qty": row.qty,
        }
        for row in doc.items
    ]


@frappe.whitelist(allow_guest=True)
def get_pcount_scan_details(
    reconciliation_id, item_code, storage_location, mobile_token=None
):
    """Return authoritative physical-count totals and immutable scan history."""
    user = _authenticate_request_user(mobile_token)
    if user == "Guest" or not user:
        frappe.throw("Session expired. Please log in again.", frappe.AuthenticationError)

    doc = frappe.get_doc("Stock Reconciliation", reconciliation_id)
    # Scanner reads are authorized by Role Profile Warehouse Access.
    ensure_scanner_warehouse_access(user, [doc.set_warehouse])
    item_code = str(item_code or "").strip()
    storage_location = str(storage_location or "").strip()
    history = frappe.get_all(
        "Physical Count Scan Transaction",
        filters={
            "reconciliation": reconciliation_id,
            "item_code": item_code,
            "storage_location": storage_location,
        },
        fields=[
            "scanned_at", "action", "quantity_change", "running_quantity",
            "storage_location", "scanner_user", "scanner_full_name", "device_id",
            "submission_id", "entry_number",
        ],
        order_by="scanned_at asc, creation asc, entry_number asc",
    )
    current_quantity = next(
        (
            _safe_float(row.qty)
            for row in doc.items
            if (row.item_code or "").strip() == item_code
            and (row.warehouse or "").strip() == (doc.set_warehouse or "").strip()
            and (row.get("location") or "").strip() == storage_location
        ),
        0.0,
    )
    total_added = sum(max(_safe_float(row.quantity_change), 0) for row in history)
    total_deducted = sum(abs(min(_safe_float(row.quantity_change), 0)) for row in history)
    return {
        "success": True,
        "reconciliation_id": reconciliation_id,
        "item_code": item_code,
        "item_name": frappe.db.get_value("Item", item_code, "item_name") or item_code,
        "warehouse": doc.set_warehouse,
        "storage_location": storage_location,
        "current_counted_quantity": current_quantity,
        "total_added": total_added,
        "total_deducted": total_deducted,
        "net_count": total_added - total_deducted,
        "first_scan_time": history[0].scanned_at if history else None,
        "last_scan_time": history[-1].scanned_at if history else None,
        "history": history,
    }


@frappe.whitelist(allow_guest=True)
def get_pcount_item_details(item_code, mobile_token=None):
    """Return authoritative ERP item details for scanner display."""
    user = _authenticate_request_user(mobile_token)
    if user == "Guest" or not user:
        frappe.throw("Session expired. Please log in again.", frappe.AuthenticationError)

    item_code = str(item_code or "").strip()
    item = frappe.db.get_value(
        "Item",
        {"name": item_code, "disabled": 0},
        ["name", "item_code", "item_name", "stock_uom"],
        as_dict=True,
    )
    if not item:
        frappe.throw(f"Item '{item_code}' does not exist or is disabled.")
    return {
        "success": True,
        "item_code": item.item_code or item.name,
        "item_name": item.item_name or item.item_code or item.name,
        "uom": item.stock_uom,
        "stock_uom": item.stock_uom,
    }


@frappe.whitelist(allow_guest=True)
def get_pcount_item_baseline(
    reconciliation_id, item_code, warehouse=None, inventory_location=None,
    batch_no=None, serial_no=None, mobile_token=None,
):
    """Return the ledger baseline used by adjustment submission."""
    user = _authenticate_request_user(mobile_token)
    if user == "Guest" or not user:
        frappe.throw("Session expired. Please log in again.", frappe.AuthenticationError)
    doc = frappe.get_doc("Stock Reconciliation", str(reconciliation_id or "").strip())
    # Scanner reads are authorized by Role Profile Warehouse Access.
    ensure_scanner_warehouse_access(user, [doc.set_warehouse])
    if doc.docstatus != 0:
        frappe.throw(f"Stock Reconciliation '{doc.name}' is not editable.")
    authoritative_warehouse = str(warehouse or doc.set_warehouse or "").strip()
    if (
        not frappe.db.exists("Warehouse", authoritative_warehouse)
        or authoritative_warehouse != str(doc.set_warehouse or "").strip()
    ):
        frappe.throw("Warehouse does not match the Stock Reconciliation Default Warehouse.")
    item_code = str(item_code or "").strip()
    item = frappe.db.get_value(
        "Item", {"name": item_code, "disabled": 0}, ["item_name", "stock_uom"], as_dict=True
    )
    if not item:
        frappe.throw(f"Item '{item_code}' does not exist or is disabled.")
    location = _resolve_storage_location({"inventoryLocation": inventory_location})
    if not location:
        frappe.throw("Storage Location is required.")
    _validate_storage_location_warehouse(location, authoritative_warehouse)
    batch_no = str(batch_no or "").strip()
    serial_no = str(serial_no or "").strip()
    if batch_no and not frappe.db.exists("Batch", {"name": batch_no, "item": item_code}):
        frappe.throw(f"Batch '{batch_no}' is invalid for {item_code}.")
    quantity = _current_inventory_quantity(
        item_code, authoritative_warehouse, location.name, batch_no, serial_no
    )
    return {
        "success": True, "reconciliation_id": doc.name, "item_code": item_code,
        "item_name": item.item_name or item_code, "warehouse": authoritative_warehouse,
        "inventory_location": location.name, "current_erp_quantity": quantity,
        "quantity": quantity, "uom": item.stock_uom,
        "batch_no": batch_no,
        "baseline_version": now_datetime(),
    }


@frappe.whitelist()
def add_manual_pcount_row(
    reconciliation_id, item_code, storage_location, physical_count,
    batch_no=None, serial_no=None,
):
    """Add an audited count missed by the scanner during For Recon."""
    reconciliation_id = str(reconciliation_id or "").strip()
    item_code = str(item_code or "").strip()
    storage_location = str(storage_location or "").strip()
    batch_no = str(batch_no or "").strip()
    serial_no = str(serial_no or "").strip()
    count = _parse_finite_number(physical_count, "physical_count", 1)
    if count < 0:
        frappe.throw("Physical Count cannot be negative.")

    savepoint = "manual_physical_count"
    frappe.db.savepoint(savepoint)
    try:
        _lock_reconciliation(reconciliation_id)
        doc = frappe.get_doc("Stock Reconciliation", reconciliation_id)
        doc.check_permission("write")
        if not doc.get("custom_physical_count") or doc.docstatus != 0:
            frappe.throw("Only a Draft Physical Count can accept manual entries.")
        if str(doc.workflow_state or "").strip() != "For Recon":
            frappe.throw("Manual Physical Count entry is only allowed during For Recon.")

        item = frappe.db.get_value(
            "Item", {"name": item_code, "disabled": 0},
            ["item_name", "stock_uom", "has_batch_no", "has_serial_no"], as_dict=True,
        )
        if not item:
            frappe.throw(f"Item '{item_code}' does not exist or is disabled.")
        location = _resolve_storage_location({"inventoryLocation": storage_location})
        if not location:
            frappe.throw("Storage Location is required.")
        _validate_storage_location_warehouse(location, doc.set_warehouse)
        if item.has_batch_no and not batch_no:
            frappe.throw(f"Batch is required for {item_code}.")
        if batch_no and not frappe.db.exists("Batch", {"name": batch_no, "item": item_code}):
            frappe.throw(f"Batch '{batch_no}' is invalid for {item_code}.")
        if item.has_serial_no and not serial_no:
            frappe.throw(f"Serial numbers are required for {item_code}.")

        key = (item_code, doc.set_warehouse, location.name, batch_no, serial_no, item.stock_uom or "")
        for row in doc.get("custom_physical_count_results") or []:
            row_key = (
                row.item_code, row.warehouse,
                row.get("location") or row.inventory_location,
                row.get("batch_no") or "", row.get("serial_no") or "", row.uom or "",
            )
            if row_key == key and row.status != "Old Count":
                frappe.throw(
                    "A Physical Count already exists for this Item and Storage Location. "
                    "Use Cost Acct Cnt to correct it."
                )

        baseline = _current_inventory_quantity(
            item_code, doc.set_warehouse, location.name, batch_no, serial_no
        )
        submission_id = f"ERP-MANUAL-{uuid.uuid4()}"
        submitted_at = now_datetime()
        user = frappe.session.user
        full_name = frappe.get_cached_value("User", user, "full_name") or user
        variance = count - baseline
        doc.append("custom_physical_count_results", {
            "submission_id": submission_id,
            "item_code": item_code,
            "item_name": item.item_name or item_code,
            "warehouse": doc.set_warehouse,
            "inventory_location": location.name,
            "inventory_location_id": location.name,
            "location": location.name,
            "location_name": location.get("location_name") or location.name,
            "uom": item.stock_uom,
            "batch_no": batch_no,
            "serial_no": serial_no,
            "erp_quantity_before": baseline,
            "expected_previous_count": 0,
            "quantity_delta": count,
            "physical_count": count,
            "cost_acct_cnt": None,
            "variance": variance,
            "adjustment_status": "Pending",
            "scanner_user": user,
            "scanner_full_name": full_name,
            "device_id": "ERP Manual",
            "counted_at": submitted_at,
            "submitted_at": submitted_at,
            "transaction_count": 1,
            "scan_history_json": json.dumps({
                "source": "ERP Manual For Recon", "entered_by": user,
                "entered_at": str(submitted_at), "physical_count": count,
            }, sort_keys=True),
            "status": "Pending adjustment",
        })
        doc.save()
        frappe.get_doc({
            "doctype": "Physical Count Scan Transaction",
            "transaction_id": f"{submission_id}:manual",
            "submission_id": submission_id,
            "entry_number": 1,
            "reconciliation": doc.name,
            "item_code": item_code,
            "warehouse": doc.set_warehouse,
            "storage_location": location.name,
            "uom": item.stock_uom,
            "action": "SUBMITTED",
            "quantity_change": count,
            "previous_quantity": 0,
            "running_quantity": count,
            "physical_count": count,
            "variance": variance,
            "scanned_at": submitted_at,
            "processed_at": submitted_at,
            "scanner_user": user,
            "scanner_full_name": full_name,
            "device_id": "ERP Manual",
        }).insert(ignore_permissions=True)
        frappe.db.commit()
        return {
            "success": True, "submission_id": submission_id,
            "item_code": item_code, "storage_location": location.name,
            "physical_count": count, "variance": variance,
        }
    except Exception:
        frappe.db.rollback(save_point=savepoint)
        raise


@frappe.whitelist(allow_guest=True)
def get_reconciliation_context(reconciliation_id=None, mobile_token=None):
    """Compatibility route retained at the scanner's established API path."""
    from qcmc_logic.api.reconciliation_context import get_reconciliation_context as get_context

    return get_context(reconciliation_id=reconciliation_id, mobile_token=mobile_token)


@frappe.whitelist(allow_guest=True)
def get_pcount_state(reconciliation_id, mobile_token=None):
    """Return authoritative ledger baselines for keys present in the draft."""
    user = _authenticate_request_user(mobile_token)
    if user == "Guest" or not user:
        frappe.throw("Session expired. Please log in again.", frappe.AuthenticationError)
    reconciliation_id = str(reconciliation_id or "").strip()
    if not reconciliation_id:
        frappe.throw("Reconciliation ID is required.")
    doc = frappe.get_doc("Stock Reconciliation", reconciliation_id)
    # Scanner reads are authorized by Role Profile Warehouse Access.
    ensure_scanner_warehouse_access(user, [doc.set_warehouse])
    entries = []
    for row in doc.items:
        item_code = (row.item_code or "").strip()
        warehouse = (row.warehouse or "").strip()
        location = (row.get("location") or "").strip()
        if not item_code or not warehouse or not location:
            continue
        if not frappe.db.exists("Item", item_code) or not frappe.db.exists("Warehouse", warehouse):
            continue
        location_code = frappe.db.get_value(
            "Storage Location", {"name": location, "disabled": 0}, "location_code"
        )
        if not location_code:
            continue
        stock_uom = (row.get("stock_uom") or frappe.db.get_value("Item", item_code, "stock_uom") or "").strip()
        display_uom = f"{stock_uom}S" if stock_uom.upper() == "PC" else stock_uom
        batch_no = (row.get("batch_no") or "").strip()
        serial_no = (row.get("serial_no") or "").strip()
        quantity = _current_inventory_quantity(
            item_code, warehouse, location, batch_no, serial_no
        )
        entries.append({
            "item_code": item_code, "warehouse": warehouse,
            "item_name": frappe.db.get_value("Item", item_code, "item_name") or item_code,
            "inventory_location": location, "inventory_location_code": location_code,
            "quantity": quantity, "uom": stock_uom,
            "batch_no": batch_no, "serial_no": serial_no,
        })
    return {"success": True, "reconciliation_id": reconciliation_id, "entries": entries}


def _get_physical_location_balances(warehouse):
    """Return authoritative positive balances for every physical location."""
    return frappe.db.sql(
        """
        with ranked_counts as (
            select pcr.item_code,
                   coalesce(nullif(pcr.location, ''), pcr.inventory_location) as location,
                   coalesce(cast(nullif(nullif(pcr.cost_acct_cnt, ''), '0.000000000') as decimal(21,9)), pcr.physical_count) as physical_count,
                   coalesce(pcr.submitted_at, sr.modified) as counted_at,
                   row_number() over (
                       partition by pcr.item_code, pcr.warehouse,
                           coalesce(nullif(pcr.location, ''), pcr.inventory_location),
                           coalesce(pcr.batch_no, ''), coalesce(pcr.serial_no, ''),
                           coalesce(pcr.uom, ''), coalesce(pcr.inventory_tag, '')
                       order by coalesce(pcr.submitted_at, sr.modified) desc, pcr.idx desc
                   ) as row_rank
            from `tabQCMC Physical Count Result` pcr
            inner join `tabStock Reconciliation` sr on sr.name = pcr.parent
            where sr.docstatus = 1 and sr.custom_physical_count = 1
              and pcr.warehouse = %(warehouse)s
        ),
        latest_counts as (
            select item_code, location, sum(physical_count) as physical_count,
                   max(counted_at) as counted_at
            from ranked_counts
            where row_rank = 1
            group by item_code, location
        ),
        candidates as (
            select wal.item_code, wal.actual_location as location
            from `tabWarehouse Allocation Location` wal
            inner join `tabWarehouse Allocation` wa on wa.name = wal.parent
            where wa.docstatus = 1 and wa.status = 'Completed'
              and wa.warehouse = %(warehouse)s and wal.status = 'VERIFIED'
            union all
            select item_code, target_location
            from `tabLocation Transfer`
            where docstatus = 1 and warehouse = %(warehouse)s
            union all
            select item_code, source_location
            from `tabLocation Transfer`
            where docstatus = 1 and warehouse = %(warehouse)s
            union all
            select item_code, location from latest_counts
        ),
        balance_state as (
            select distinct candidate.item_code, candidate.location,
                   coalesce(latest.physical_count, 0)
                   + coalesce((
                       select sum(wal.actual_qty)
                       from `tabWarehouse Allocation Location` wal
                       inner join `tabWarehouse Allocation` wa on wa.name = wal.parent
                       where wa.docstatus = 1 and wa.status = 'Completed'
                         and wa.warehouse = %(warehouse)s
                         and wal.item_code = candidate.item_code
                         and wal.status = 'VERIFIED'
                         and wal.actual_location = candidate.location
                         and (latest.counted_at is null
                              or coalesce(wa.completed_at, wa.modified) > latest.counted_at)
                   ), 0)
                   + coalesce((
                       select sum(case
                           when transfer.target_location = candidate.location then transfer.quantity
                           when transfer.source_location = candidate.location then -transfer.quantity
                           else 0 end)
                       from `tabLocation Transfer` transfer
                       where transfer.docstatus = 1
                         and transfer.warehouse = %(warehouse)s
                         and transfer.item_code = candidate.item_code
                         and (transfer.source_location = candidate.location
                              or transfer.target_location = candidate.location)
                         and (latest.counted_at is null
                              or transfer.transferred_at > latest.counted_at)
                   ), 0) as quantity
            from candidates candidate
            left join latest_counts latest
              on latest.item_code = candidate.item_code
             and latest.location = candidate.location
            where coalesce(candidate.location, '') != ''
        )
        select balance.item_code, item.item_name, item.stock_uom,
               %(warehouse)s as warehouse, balance.location, balance.quantity
        from balance_state balance
        inner join `tabItem` item on item.name = balance.item_code
        where balance.quantity > 0.000000001
        order by item.item_name, balance.item_code, balance.location
        """,
        {"warehouse": warehouse},
        as_dict=True,
    )


def _get_unallocated_warehouse_balances(warehouse, physical_balances=None):
    """Return positive ERP Bin stock not represented by a physical location."""
    physical_balances = (
        physical_balances
        if physical_balances is not None
        else _get_physical_location_balances(warehouse)
    )
    located_by_item = defaultdict(float)
    for balance in physical_balances:
        located_by_item[balance.item_code] += _safe_float(balance.quantity)

    bin_rows = frappe.db.sql(
        """
        select bin.item_code, coalesce(item.item_name, bin.item_code) as item_name,
               item.stock_uom, bin.warehouse, bin.actual_qty
        from `tabBin` bin
        inner join `tabItem` item on item.name = bin.item_code
        where bin.warehouse = %(warehouse)s
          and bin.actual_qty > 0.000000001
        """,
        {"warehouse": warehouse},
        as_dict=True,
    )
    unallocated = []
    for row in bin_rows:
        quantity = _safe_float(row.actual_qty) - located_by_item[row.item_code]
        if quantity > 0.000000001:
            unallocated.append(frappe._dict(
                item_code=row.item_code,
                item_name=row.item_name or row.item_code,
                stock_uom=row.stock_uom,
                warehouse=row.warehouse,
                quantity=quantity,
            ))
    return unallocated


@frappe.whitelist()
def get_pcount_reconciliation_review(reconciliation_id):
    """Return book-stock exceptions for ERP reviewers, never scanner clients."""
    reconciliation_id = str(reconciliation_id or "").strip()
    doc = frappe.get_doc("Stock Reconciliation", reconciliation_id)
    doc.check_permission("read")
    if not doc.get("custom_physical_count"):
        frappe.throw("This Stock Reconciliation is not a Physical Count.")
    warehouse = str(doc.set_warehouse or "").strip()
    if not warehouse:
        frappe.throw("Default Warehouse is required.")

    counted_keys = set()
    counted_locations = set()
    scanned_items = set()
    for result in doc.get("custom_physical_count_results") or []:
        location = str(result.get("location") or result.inventory_location or "").strip()
        if (
            not result.item_code or not location
            or str(result.submission_id or "").startswith("AUTO-ZERO-")
        ):
            continue
        key = (str(result.item_code).strip(), str(result.warehouse or warehouse).strip(), location)
        counted_keys.add(key)
        counted_locations.add(location)
        scanned_items.add(key[0])

    balances = _get_physical_location_balances(warehouse)
    unscanned = []
    for balance in balances:
        key = (balance.item_code, balance.warehouse, balance.location)
        if key in counted_keys:
            continue
        unscanned.append({
            "item_code": balance.item_code,
            "item_name": balance.item_name or balance.item_code,
            "warehouse": balance.warehouse,
            "storage_location": balance.location,
            "location_name": frappe.db.get_value(
                "Storage Location", balance.location, "location_name"
            ) or balance.location,
            "book_quantity": _safe_float(balance.quantity),
            "uom": balance.stock_uom,
            "item_never_scanned": balance.item_code not in scanned_items,
            "reason": (
                "Item never scanned" if balance.item_code not in scanned_items
                else "Item not counted" if balance.location in counted_locations
                else "Location not counted"
            ),
        })

    locations = frappe.get_all(
        "Storage Location",
        filters={"custom_warehouse": warehouse, "disabled": 0, "is_group": 0},
        fields=["name", "location_code", "location_name", "location_type"],
        order_by="location_name, name",
    )
    listed_locations = {row["storage_location"] for row in unscanned}
    for location in locations:
        if location.name in counted_locations or location.name in listed_locations:
            continue
        unscanned.append({
            "item_code": "",
            "item_name": "",
            "warehouse": warehouse,
            "storage_location": location.name,
            "location_code": location.location_code or "",
            "location_name": location.location_name or location.name,
            "location_type": location.location_type or "",
            "book_quantity": 0,
            "uom": "",
            "item_never_scanned": False,
            "reason": "No ERP stock",
        })

    unscanned.sort(key=lambda row: (
        str(row.get("location_name") or row.get("storage_location") or "").lower(),
        str(row.get("item_code") or "").lower(),
    ))
    locations_without_counts = {
        location.name for location in locations if location.name not in counted_locations
    }

    return {
        "success": True,
        "reconciliation_id": doc.name,
        "warehouse": warehouse,
        "counted_location_count": len(counted_locations),
        "unscanned_balance_count": len(unscanned),
        "location_without_count_count": len(locations_without_counts),
        "never_scanned_item_count": len({
            row["item_code"] for row in unscanned if row["item_never_scanned"]
        }),
        "unscanned_balances": unscanned,
    }


@frappe.whitelist()
def check_items_location(reconciliation_id):
    """Check the latest Physical Count placements against active Putaway Rules."""
    from qcmc_logic.api.warehouse_allocation import _committed_location_quantities

    doc = frappe.get_doc("Stock Reconciliation", str(reconciliation_id or "").strip())
    doc.check_permission("read")
    if not doc.get("custom_physical_count"):
        frappe.throw("This Stock Reconciliation is not a Physical Count.")

    latest = {}
    for row in doc.get("custom_physical_count_results") or []:
        location = str(row.get("location") or row.inventory_location or "").strip()
        warehouse = str(row.warehouse or doc.set_warehouse or "").strip()
        if not row.item_code or not location or row.status == "Old Count":
            continue
        latest[(row.item_code, warehouse, location)] = row

    results = []
    occupancy_cache = {}
    for (item_code, warehouse, location_name), count in latest.items():
        effective_count = _effective_physical_count(count)
        if effective_count <= 0:
            continue
        location = frappe.db.get_value(
            "Storage Location", location_name,
            ["location_name", "location_type", "custom_warehouse", "custom_restricted_item", "disabled"],
            as_dict=True,
        )
        has_no_item_rule = frappe.get_meta("Putaway Rule").has_field("custom_no_item_restriction")
        rule_fields = ["name", "item_code", "priority", "capacity"]
        if has_no_item_rule:
            rule_fields.append("custom_no_item_restriction")
        matching_rules = frappe.get_all(
            "Putaway Rule",
            filters={"warehouse": warehouse, "location": location_name, "disable": 0},
            or_filters=[
                {"item_code": item_code},
                {"custom_no_item_restriction": 1},
            ] if has_no_item_rule else {"item_code": item_code},
            fields=rule_fields,
            order_by="priority asc, name asc",
        )
        matching_rules = sorted(
            matching_rules,
            key=lambda row: (
                0 if str(row.get("item_code") or "").strip() == str(item_code or "").strip() else 1,
                row.priority or 0,
                row.name,
            ),
        )
        rule = matching_rules[0] if matching_rules else None
        expected_rules = frappe.get_all(
            "Putaway Rule",
            filters={"warehouse": warehouse, "disable": 0},
            or_filters=[
                {"item_code": item_code},
                {"custom_no_item_restriction": 1},
            ] if has_no_item_rule else {"item_code": item_code},
            fields=["name", "item_code", "location", "priority", "capacity"],
            order_by="priority asc, name asc",
            limit_page_length=0,
        )
        expected_rules = sorted(
            expected_rules,
            key=lambda row: (
                0 if str(row.get("item_code") or "").strip() == str(item_code or "").strip() else 1,
                row.priority or 0,
                row.name,
            ),
        )
        expected_locations = [row.location for row in expected_rules if row.location]
        occupancy = occupancy_cache.setdefault(
            (item_code, warehouse), _committed_location_quantities(item_code, warehouse),
        )
        available_rules = []
        for expected_rule in expected_rules:
            available = max(
                _safe_float(expected_rule.capacity) - _safe_float(occupancy.get(expected_rule.location, 0)),
                0,
            )
            if available > 1e-9:
                expected_rule.available_capacity = available
                available_rules.append(expected_rule)
        available_locations = [row.location for row in available_rules]
        if not location or location.disabled or location.custom_warehouse != warehouse:
            status, message = "INVALID", "Storage Location is disabled or belongs to another Warehouse."
        elif location.custom_restricted_item and location.custom_restricted_item != item_code:
            status, message = "ITEM MISMATCH", f"Location is restricted to {location.custom_restricted_item}."
        elif rule and _safe_float(rule.capacity) > 0 and effective_count > _safe_float(rule.capacity):
            status, message = "OVER CAPACITY", (
                f"Counted quantity exceeds Putaway Rule capacity by "
                f"{effective_count - _safe_float(rule.capacity):,.3f} {count.uom or ''}."
            )
        elif rule:
            status, message = "VALID", f"Allowed by Putaway Rule {rule.name}."
        elif location.location_type == "Open Area" and not location.custom_restricted_item:
            status, message = "OPEN AREA", "Allowed as unrestricted Open Area fallback."
        elif available_locations:
            status, message = "WRONG LOCATION", (
                f"Item is stored at {location_name}, but its active Putaway Rule assigns it to "
                f"{', '.join(available_locations)}."
            )
        elif expected_locations:
            status, message = "WRONG LOCATION", (
                "All configured Putaway Rule locations are currently full. "
                "Use an allowed Open Area."
            )
        else:
            status, message = "NO PUTAWAY RULE", "No active Putaway Rule allows this Item at this Location."
        results.append({
            "item_code": item_code,
            "item_name": count.item_name or frappe.db.get_value("Item", item_code, "item_name") or item_code,
            "warehouse": warehouse,
            "storage_location": location_name,
            "location_name": location.location_name if location else location_name,
            "physical_count": effective_count,
            "uom": count.uom or "",
            "status": status,
            "message": message,
            "putaway_rule": rule.name if rule else ", ".join(row.name for row in available_rules),
            "priority": rule.priority if rule else available_rules[0].priority if available_rules else None,
            "capacity": _safe_float(rule.capacity) if rule else None,
            "expected_locations": expected_locations,
            "available_locations": [{
                "location": row.location,
                "putaway_rule": row.name,
                "priority": row.priority,
                "available_capacity": row.available_capacity,
            } for row in available_rules],
        })
    results.sort(key=lambda row: (row["status"] == "VALID", row["status"] == "OPEN AREA", row["storage_location"], row["item_code"]))
    invalid_statuses = {"INVALID", "ITEM MISMATCH", "WRONG LOCATION", "NO PUTAWAY RULE", "OVER CAPACITY"}
    return {
        "success": True,
        "reconciliation_id": doc.name,
        "rows": results,
        "checked_count": len(results),
        "valid_count": sum(row["status"] in {"VALID", "OPEN AREA"} for row in results),
        "issue_count": sum(row["status"] in invalid_statuses for row in results),
    }
