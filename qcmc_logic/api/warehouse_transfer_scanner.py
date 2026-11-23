"""Read-only Warehouse Transfer scanner context.

Provides authoritative rows for a new scanner Checker workflow without
changing Warehouse Transfer documents or Storage Allocations.
"""
import re
from decimal import Decimal

import frappe

from qcmc_logic.api.warehouse_workflow import (
    WorkflowError,
    authenticated_user,
    error_response,
)
from qcmc_logic.utils import ensure_scanner_warehouse_access


def _clean_wts(value):
    name = str(value or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,139}", name):
        raise WorkflowError("INVALID_WTS_QR", "Scan a Warehouse Transfer Slip QR containing its exact WTS number.")
    return name


@frappe.whitelist(allow_guest=True, methods=["POST"])
def get_context(warehouse_transfer, mobile_token=None):
    try:
        user = authenticated_user(mobile_token)
        name = _clean_wts(warehouse_transfer)
        if not frappe.db.exists("Warehouse Transfer", name):
            raise WorkflowError("WTS_NOT_FOUND", "Warehouse Transfer was not found.")
        doc = frappe.get_doc("Warehouse Transfer", name)
        if doc.docstatus == 2:
            raise WorkflowError("WTS_CANCELLED", "This Warehouse Transfer is cancelled.")
        if doc.docstatus != 1:
            raise WorkflowError("WTS_NOT_SUBMITTED", "Submit the Warehouse Transfer in ERPNext before scanner checking.")
        # Warehouse checker and receiving picker may belong to different
        # warehouses; a permitted operator needs access to at least one side
        # to inspect the WTS, never blanket access to all transfers.
        permitted = False
        for warehouse in (doc.source_warehouse, doc.target_warehouse):
            if not warehouse:
                continue
            try:
                ensure_scanner_warehouse_access(user, [warehouse], require_transact=False)
                permitted = True
                break
            except frappe.PermissionError:
                continue
        if not permitted:
            raise WorkflowError("WAREHOUSE_PERMISSION_DENIED", "Warehouse access denied.", status=403)
        if doc.transfer_status == "Received":
            raise WorkflowError("WTS_ALREADY_RECEIVED", "Warehouse Transfer has already been received.")

        items = []
        for row in doc.get("transfer_items") or []:
            if not row.item_code:
                continue
            items.append({
                "row_id": row.name,
                "item_code": row.item_code,
                "item_name": row.item_name or row.item_code,
                "uom": row.uom or "",
                "issued_quantity": float(row.issued_qty or 0),
                "received_quantity": float(row.received_qty or 0),
            })
        if not items:
            raise WorkflowError("WTS_EMPTY", "Warehouse Transfer has no items to check.")
        return {
            "success": True,
            "warehouse_transfer": doc.name,
            "source_warehouse": doc.source_warehouse,
            "target_warehouse": doc.target_warehouse,
            "transfer_status": doc.transfer_status,
            "docstatus": doc.docstatus,
            "items": items,
            "checker_verification_supported": True,
            "message": "Check actual Received Qty; confirmed changes update WTS and enabled Putaway allocation before handover.",
        }
    except WorkflowError as exc:
        return error_response(exc)
    except Exception:
        frappe.log_error(frappe.get_traceback(), "warehouse_transfer_scanner.get_context")
        return error_response(WorkflowError("ERP_VALIDATION_FAILED", "Unable to load Warehouse Transfer."))


@frappe.whitelist(allow_guest=True, methods=["POST"])
def validate_checker_qr(warehouse_transfer, checker_qr, mobile_token=None):
    """Validate an Assign Checker QR against a live WTS, without recording approval.

    This deliberately does not create a handover or update any stock records.
    The final WTS checker confirmation must revalidate quantities and identity
    atomically in a separate, idempotent write endpoint.
    """
    try:
        user = authenticated_user(mobile_token)
        name = _clean_wts(warehouse_transfer)

        # Use the same QR resolver already used by Manufacturing, not a
        # separate parser that could accept plain names or disabled IDs.
        from qcmc_logic.api.warehouse_handover import _resolve_checker_qr

        if not frappe.db.exists("Warehouse Transfer", name):
            raise WorkflowError("WTS_NOT_FOUND", "Warehouse Transfer was not found.")
        doc = frappe.get_doc("Warehouse Transfer", name)
        if doc.docstatus != 1 or doc.transfer_status == "Received":
            raise WorkflowError(
                "WTS_NOT_OPEN",
                "The Warehouse Transfer must be submitted and not already received.",
            )

        # A logged-in scanner operator must have access to at least one side.
        operator_permitted = False
        for warehouse in (doc.source_warehouse, doc.target_warehouse):
            if not warehouse:
                continue
            try:
                ensure_scanner_warehouse_access(user, [warehouse], require_transact=False)
                operator_permitted = True
                break
            except frappe.PermissionError:
                pass
        if not operator_permitted:
            raise WorkflowError("WAREHOUSE_PERMISSION_DENIED", "Warehouse access denied.", status=403)

        resolved = _resolve_checker_qr(checker_qr, authenticated_checker_user=user)
        checker = resolved.employee
        # The Assign Checker DocType allows a manually entered Name without
        # an Employee link. The QR resolver validates the enabled record and,
        # when present, the linked Employee's active status.
        # Agency checkers can have an active Employee without an ERPNext User.
        # Authenticate/authorize the scanner operator above; the printed
        # Assign Checker QR identifies the real checker, not a login account.
        # If a checker does have an ERPNext User, validate warehouse access
        # through that account as an additional check.
        if checker and checker.user_id:
            try:
                ensure_scanner_warehouse_access(checker.user_id, [doc.source_warehouse], require_transact=False)
            except frappe.PermissionError:
                raise WorkflowError(
                    "CHECKER_NOT_AUTHORIZED",
                    "The assigned Checker has no access to the source warehouse.",
                    status=403,
                )
        return {
            "success": True,
            "warehouse_transfer": doc.name,
            "checker_id": resolved.assign_checker.name,
            "checker_name": resolved.assign_checker.checker_name,
            "checker_employee": checker.name if checker else "",
            "validated_only": True,
            "handover_created": False,
            "message": "Checker identity validated. Warehouse Transfer handover creation is not yet enabled.",
        }
    except WorkflowError as exc:
        return error_response(exc)
    except Exception:
        frappe.log_error(frappe.get_traceback(), "warehouse_transfer_scanner.validate_checker_qr")
        return error_response(WorkflowError("ERP_VALIDATION_FAILED", "Unable to validate the Checker QR."))

# WTS uses the same Assign Checker QR resolver as Manufacturing, but has its
# own durable Handover record because the Manufacturing batch only owns Stock
# Entry rows. These endpoints never submit Manufacturing Stock Entries.
def _wts_fingerprint(doc):
    import hashlib
    import json

    data = {
        "name": doc.name,
        "modified": str(doc.modified),
        "docstatus": doc.docstatus,
        "transfer_status": doc.transfer_status,
        "source": doc.source_warehouse,
        "target": doc.target_warehouse,
        "items": [
            [row.name, row.item_code, str(row.issued_qty or 0), row.uom or ""]
            for row in (doc.get("transfer_items") or [])
        ],
    }
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode("utf-8")).hexdigest()


def _verified_counts(doc, rows):
    from decimal import Decimal, InvalidOperation
    from qcmc_logic.api.warehouse_workflow import parse_json

    parsed = parse_json(rows, [])
    if not isinstance(parsed, list):
        raise WorkflowError("INVALID_CHECKER_ROWS", "Checked quantities must be an array.")
    expected = {row.name: row for row in (doc.get("transfer_items") or []) if row.item_code}
    if len(parsed) != len(expected):
        raise WorkflowError("CHECKER_QUANTITY_MISMATCH", "Every WTS item row must be checked exactly once.")
    found = {}
    for value in parsed:
        if not isinstance(value, dict):
            raise WorkflowError("INVALID_CHECKER_ROWS", "Each checked row must be an object.")
        row_id = str(value.get("row_id") or "").strip()
        if not row_id or row_id in found or row_id not in expected:
            raise WorkflowError("INVALID_CHECKER_ROWS", "The checked item rows do not match the current WTS.")
        try:
            quantity = Decimal(str(value.get("checked_quantity")))
        except (InvalidOperation, ValueError, TypeError):
            raise WorkflowError("INVALID_QUANTITY", "A checked quantity is not a valid number.")
        if not quantity.is_finite() or quantity < 0:
            raise WorkflowError("INVALID_QUANTITY", "Checked quantity cannot be negative or non-finite.")
        # The Checker records the physical count even when short/excess.
        # Variance is held for reconciliation before any ERP stock receipt.
        found[row_id] = str(quantity)
    return found


def _check_date(value):
    from datetime import date
    from frappe.utils import getdate, nowdate
    raw = str(value or "").strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        raise WorkflowError("CHECK_DATE_REQUIRED", "Confirm the physical checking date (YYYY-MM-DD).")
    try:
        # date.fromisoformat raises ValueError for invalid calendar dates.
        # frappe.utils.getdate instead raises frappe.ValidationError.
        checked = date.fromisoformat(raw)
    except ValueError:
        raise WorkflowError("INVALID_CHECK_DATE", "Invalid physical checking date.")
    if checked > getdate(nowdate()):
        raise WorkflowError("INVALID_CHECK_DATE", "Checking date must be a valid date, not in the future.")
    return raw


def _validated_extra_items(doc, rows):
    from decimal import Decimal, InvalidOperation
    from qcmc_logic.api.warehouse_workflow import parse_json

    values = parse_json(rows, [])
    if not isinstance(values, list) or len(values) > 100:
        raise WorkflowError("INVALID_EXTRA_ITEMS", "Extra items must be an array of at most 100 rows.")
    existing = {str(r.item_code).upper() for r in (doc.get("transfer_items") or []) if r.item_code}
    found = set()
    extra = []
    for value in values:
        if not isinstance(value, dict):
            raise WorkflowError("INVALID_EXTRA_ITEMS", "Each extra item must have item code and physical quantity.")
        code = str(value.get("item_code") or "").strip()
        if not code or code.upper() in existing or code.upper() in found:
            raise WorkflowError("INVALID_EXTRA_ITEMS", "Extra item code is missing, duplicated, or already on the WTS.")
        item = frappe.db.get_value("Item", code, ["name", "item_name", "stock_uom", "disabled", "is_stock_item"], as_dict=True)
        if not item or item.disabled or not item.is_stock_item:
            raise WorkflowError("INVALID_EXTRA_ITEMS", "Extra item must be an enabled stock Item in ERPNext: " + code)
        try:
            qty = Decimal(str(value.get("checked_quantity")))
        except (ValueError, InvalidOperation, TypeError):
            raise WorkflowError("INVALID_QUANTITY", "Extra item has an invalid physical quantity.")
        if not qty.is_finite() or qty <= 0:
            raise WorkflowError("INVALID_QUANTITY", "Extra item quantity must be greater than zero.")
        found.add(code.upper())
        extra.append({
            "item_code": item.name,
            "item_name": item.item_name or item.name,
            "stock_uom": item.stock_uom,
            "checked_quantity": str(qty),
        })
    return sorted(extra, key=lambda v: v["item_code"])


@frappe.whitelist(allow_guest=True, methods=["POST"])
def validate_extra_item(warehouse_transfer, item_code, mobile_token=None):
    """Look up an enabled stock Item for an unexpected physical delivery."""
    try:
        user = authenticated_user(mobile_token)
        name = _clean_wts(warehouse_transfer)
        doc = frappe.get_doc("Warehouse Transfer", name)
        if doc.docstatus != 1 or doc.transfer_status != "Transferred":
            raise WorkflowError("WTS_NOT_OPEN", "WTS must be submitted and Transferred.")
        permitted = False
        for warehouse in (doc.source_warehouse, doc.target_warehouse):
            try:
                ensure_scanner_warehouse_access(user, [warehouse], require_transact=False)
                permitted = True
                break
            except frappe.PermissionError:
                continue
        if not permitted:
            raise WorkflowError("WAREHOUSE_PERMISSION_DENIED", "Warehouse access denied.", status=403)
        values = _validated_extra_items(doc, [{"item_code": item_code, "checked_quantity": 1}])
        return {"success": True, "item": values[0]}
    except WorkflowError as exc:
        return error_response(exc)
    except Exception:
        frappe.log_error(frappe.get_traceback(), "warehouse_transfer_scanner.validate_extra_item")
        return error_response(WorkflowError("ERP_VALIDATION_FAILED", "Unable to look up the extra Item."))


def _save_checked_receipt(doc, counts, extra):
    """Write physical receipts while Transferred; never post stock here.

    An existing issued row keeps Issued Qty and reference fields. Additional
    delivered Items are receiver-added rows with Issued Qty zero, matching
    Warehouse Transfer's native receive-side validation. Saving invokes the
    existing WTS Putaway synchronization when selected.
    """
    present = {str(row.item_code).upper() for row in doc.get("transfer_items") or [] if row.item_code}
    for row in doc.get("transfer_items") or []:
        if row.name in counts:
            row.received_qty = float(Decimal(counts[row.name]))
    for item in extra:
        if str(item["item_code"]).upper() in present:
            continue
        doc.append("transfer_items", {
            "item_code": item["item_code"],
            "item_name": item["item_name"],
            "uom": item["stock_uom"],
            "issued_qty": 0,
            "received_qty": float(Decimal(item["checked_quantity"])),
        })
    doc.flags.qcmc_wts_checker_sync = True
    doc.save(ignore_permissions=True)
    # Reload so Handover fingerprint includes persisted child row names and
    # modified timestamp after allocation / WTS hooks have run.
    return frappe.get_doc("Warehouse Transfer", doc.name)


def _same_check_request(handover, rows, extra_items, checked_on):
    """Idempotent retry without re-adding the extra stock rows."""
    from qcmc_logic.api.warehouse_workflow import parse_json
    from decimal import Decimal, InvalidOperation
    import json

    expected = json.loads(handover.verified_quantities_json or "{}")
    actual_rows = parse_json(rows, [])
    if not isinstance(actual_rows, list) or len(actual_rows) != len(expected):
        return False
    seen = {}
    for row in actual_rows:
        if not isinstance(row, dict):
            return False
        row_id = str(row.get("row_id") or "").strip()
        if row_id not in expected or row_id in seen:
            return False
        try:
            value = Decimal(str(row.get("checked_quantity")))
        except (ValueError, InvalidOperation, TypeError):
            return False
        if not value.is_finite() or value < 0:
            return False
        seen[row_id] = str(value)
    if any(Decimal(seen[key]) != Decimal(value) for key, value in expected.items()):
        return False
    raw_extra = parse_json(extra_items, [])
    saved_extra = json.loads(handover.extra_items_json or "[]")
    if not isinstance(raw_extra, list) or len(raw_extra) != len(saved_extra):
        return False
    normalized = {}
    for item in raw_extra:
        if not isinstance(item, dict):
            return False
        code = str(item.get("item_code") or "").strip()
        try:
            quantity = Decimal(str(item.get("checked_quantity")))
        except (InvalidOperation, ValueError, TypeError):
            return False
        if code in normalized or not quantity.is_finite() or quantity <= 0:
            return False
        normalized[code] = quantity
    return (
        str(handover.check_date or "") == checked_on
        and len(normalized) == len(saved_extra)
        and all(item["item_code"] in normalized and
                normalized[item["item_code"]] == Decimal(str(item["checked_quantity"]))
                for item in saved_extra)
    )


def _wts_handover_qr(handover):
    import json

    token = handover.get_password("handover_token", raise_exception=False)
    if not token:
        raise WorkflowError("INVALID_HANDOVER_QR", "Handover QR token is missing.")
    return json.dumps({
        "type": "QCMC_WTS_HANDOVER",
        "version": 1,
        "warehouse_transfer": handover.warehouse_transfer,
        "token": token,
        "expires_at": str(handover.expires_at),
    }, separators=(",", ":"))


@frappe.whitelist(allow_guest=True, methods=["POST"])
def confirm_checker(warehouse_transfer, checker_qr, checked_rows, request_id, device_id=None, mobile_token=None, extra_items=None, check_date=None):
    """Persist verified WTS Checker, then return a tokenized Picker handover QR.

    The complete WTS row snapshot is checked while its record is locked. The
    existing Manufacturing Checker resolver is intentionally reused unchanged.
    """
    savepoint = "qcmc_wts_confirm_checker"
    started = False
    try:
        import json
        import secrets
        from datetime import timedelta
        from frappe.utils import get_datetime, now_datetime
        from qcmc_logic.api.warehouse_workflow import active_employee, request_uuid
        from qcmc_logic.api.warehouse_handover import _resolve_checker_qr

        user = authenticated_user(mobile_token)
        active_employee(user)
        name = _clean_wts(warehouse_transfer)
        if not frappe.db.exists("DocType", "Scanner WTS Handover"):
            raise WorkflowError("SETUP_REQUIRED", "Run the Scanner WTS Handover setup patch before using this workflow.")
        if not device_id:
            raise WorkflowError("DEVICE_ID_REQUIRED", "Scanner Device ID is required.")
        # A single locked WTS can have only one linked handover. Retrying a
        # matching confirmation returns the same encrypted-at-rest QR token.
        # Never store bearer handover tokens in a generic request audit log.
        request_uuid(request_id)
        from qcmc_logic.api.warehouse_workflow import parse_json
        parsed_rows = parse_json(checked_rows, [])
        frappe.db.savepoint(savepoint)
        started = True

        frappe.db.sql("select name from `tabWarehouse Transfer` where name=%s for update", name)
        if not frappe.db.exists("Warehouse Transfer", name):
            raise WorkflowError("WTS_NOT_FOUND", "Warehouse Transfer was not found.")
        doc = frappe.get_doc("Warehouse Transfer", name)
        if doc.docstatus != 1 or doc.transfer_status == "Received":
            raise WorkflowError("WTS_NOT_OPEN", "Warehouse Transfer must be submitted and not received.")
        try:
            ensure_scanner_warehouse_access(user, [doc.source_warehouse], require_transact=False)
        except frappe.PermissionError:
            raise WorkflowError("WAREHOUSE_PERMISSION_DENIED", "Checker operator cannot access this source warehouse.", status=403)

        verified = _resolve_checker_qr(checker_qr, authenticated_checker_user=user)
        checker = verified.employee
        # Name-only Assign Checker records are valid; Employee Link is optional.
        # Preserve Employee identity for agency checkers with no ERPNext User.
        # The authenticated scanner operator is authorized for the source
        # warehouse above; an optional linked ERPNext User is checked too.
        if checker and checker.user_id:
            try:
                ensure_scanner_warehouse_access(checker.user_id, [doc.source_warehouse], require_transact=False)
            except frappe.PermissionError:
                raise WorkflowError("CHECKER_NOT_AUTHORIZED", "Assign Checker cannot access this warehouse.", status=403)
        checked_on = _check_date(check_date)
        resumed = False
        existing = frappe.db.exists("Scanner WTS Handover", {"warehouse_transfer": name})
        if existing:
            handover = frappe.get_doc("Scanner WTS Handover", existing)
            if handover.checker != verified.assign_checker.name:
                raise WorkflowError("CHECKER_VERIFICATION_CONFLICT", "WTS was checked by another assigned Checker.", status=409)
            if handover.source_fingerprint != _wts_fingerprint(doc):
                raise WorkflowError("SOURCE_DOCUMENT_CHANGED", "WTS changed since the saved Checker receipt. Review it in ERPNext before continuing.", status=409)
            # Retrying a previously confirmed receipt must not become trapped
            # merely because the device defaults to today's date or the WTS
            # now includes receiver-added rows. Resume the authoritative
            # saved Checker record; NEVER overwrite its quantities/date or
            # append extra Items a second time.
            resumed = True
            if handover.status == "COMPLETED":
                raise WorkflowError("WTS_ALREADY_RECEIVED", "This WTS handover is already complete.")
            if handover.status == "CANCELLED":
                raise WorkflowError("INVALID_HANDOVER_STATUS", "This WTS handover was cancelled.")
            extra = json.loads(handover.extra_items_json or "[]")
            # Older CHECKED handovers stored the physical audit but did not
            # write WTS Received Qty. Upgrade only an unchanged, still-open
            # handover after verifying an identical check request.
            saved_counts = json.loads(handover.verified_quantities_json or "{}")
            actual_codes = {str(row.item_code).upper() for row in doc.get("transfer_items") or []}
            missing_extra = any(str(item["item_code"]).upper() not in actual_codes for item in extra)
            missing_counts = any(
                Decimal(str(row.received_qty or 0)) != Decimal(saved_counts[row.name])
                for row in (doc.get("transfer_items") or []) if row.name in saved_counts
            )
            if missing_extra or missing_counts:
                doc = _save_checked_receipt(doc, saved_counts, extra)
                handover.source_fingerprint = _wts_fingerprint(doc)
                handover.save(ignore_permissions=True)
            expires = get_datetime(handover.expires_at) if handover.expires_at else None
            if not expires or expires <= now_datetime():
                handover.handover_token = secrets.token_urlsafe(32)
                handover.expires_at = now_datetime() + timedelta(hours=24)
                handover.save(ignore_permissions=True)
        else:
            counts = _verified_counts(doc, parsed_rows)
            extra = _validated_extra_items(doc, extra_items)
            variance = bool(extra) or any(
                Decimal(counts[row.name]) != Decimal(str(row.issued_qty or 0))
                for row in (doc.get("transfer_items") or []) if row.item_code
            )
            # Stage received quantities and receiver-added rows on the actual
            # submitted WTS. The before-update-after-submit hook regenerates
            # Putaway reservations from those receiving quantities when opted in.
            doc = _save_checked_receipt(doc, counts, extra)
            fingerprint = _wts_fingerprint(doc)
            handover = frappe.get_doc({
                "doctype": "Scanner WTS Handover",
                "warehouse_transfer": name,
                "status": "CHECKED",
                "source_warehouse": doc.source_warehouse,
                "target_warehouse": doc.target_warehouse,
                "checker": verified.assign_checker.name,
                "checker_employee": checker.name if checker else "",
                "checker_user": user,
                "checked_at": now_datetime(),
                "verified_quantities_json": json.dumps(counts, sort_keys=True),
                "extra_items_json": json.dumps(extra, sort_keys=True),
                "check_date": checked_on,
                "has_discrepancy": int(variance),
                "source_fingerprint": fingerprint,
                "handover_token": secrets.token_urlsafe(32),
                "expires_at": now_datetime() + timedelta(hours=24),
                "device_id": str(device_id),
            })
            handover.insert(ignore_permissions=True)

        response = {
            "success": True,
            "status": handover.status,
            "warehouse_transfer": name,
            "batch_id": handover.name,
            "checker": verified.assign_checker.checker_name,
            "checker_id": verified.assign_checker.name,
            "checked_at": str(handover.checked_at),
            "check_date": str(handover.check_date or ""),
            "resumed_existing_check": resumed,
            "message": ("Existing confirmed WTS check resumed; saved quantities and checking date were retained."
                        if resumed else "WTS quantities and checking date saved."),
            "has_discrepancy": bool(handover.has_discrepancy),
            "extra_items": extra,
            "handover_qr": _wts_handover_qr(handover),
            "expires_at": str(handover.expires_at),
        }
        return response
    except WorkflowError as exc:
        if started:
            frappe.db.rollback(save_point=savepoint)
        return error_response(exc)
    except Exception:
        if started:
            frappe.db.rollback(save_point=savepoint)
        frappe.log_error(frappe.get_traceback(), "warehouse_transfer_scanner.confirm_checker")
        return error_response(WorkflowError("ERP_VALIDATION_FAILED", "Could not confirm WTS Checker. No handover or receipt update saved."))


@frappe.whitelist(allow_guest=True, methods=["POST"])
def get_picker_context(handover_qr, mobile_token=None):
    """Validate a WTS handover QR for the existing Picker/Allocation screen."""
    try:
        import json
        import secrets
        from frappe.utils import get_datetime, now_datetime
        from qcmc_logic.api.warehouse_workflow import parse_json, active_employee

        user = authenticated_user(mobile_token)
        active_employee(user)
        # The scanner's Checker and Picker buttons are workflow choices, not
        # ERPNext role assignments. One operator may perform both stages.
        payload = parse_json(handover_qr, {})
        if not isinstance(payload, dict) or payload.get("type") != "QCMC_WTS_HANDOVER" or payload.get("version") != 1:
            raise WorkflowError("INVALID_HANDOVER_QR", "Scan a valid Warehouse Transfer Handover QR.")
        name = _clean_wts(payload.get("warehouse_transfer"))
        if not frappe.db.exists("Scanner WTS Handover", name):
            raise WorkflowError("HANDOVER_NOT_FOUND", "WTS Handover not found.")
        handover = frappe.get_doc("Scanner WTS Handover", name)
        stored = handover.get_password("handover_token", raise_exception=False) or ""
        if not stored or not secrets.compare_digest(stored, str(payload.get("token") or "")):
            raise WorkflowError("INVALID_HANDOVER_QR", "Handover QR token is invalid.", status=403)
        if not handover.expires_at or get_datetime(handover.expires_at) < now_datetime():
            raise WorkflowError("INVALID_HANDOVER_QR", "Handover QR expired. Ask the Checker to regenerate it.", status=403)
        if handover.status not in {"CHECKED", "ALLOCATION_CREATED"}:
            raise WorkflowError("INVALID_HANDOVER_STATUS", "Handover is no longer available.")
        # Reading a Handover must not demand a second ERPNext role or
        # destination Transact permission. Allow a logged-in operator with
        # existing scanner read access to either side of this transfer,
        # including the same operator who checked its source warehouse.
        permitted = False
        for warehouse in (handover.source_warehouse, handover.target_warehouse):
            if not warehouse:
                continue
            try:
                ensure_scanner_warehouse_access(user, [warehouse], require_transact=False)
                permitted = True
                break
            except frappe.PermissionError:
                continue
        if not permitted:
            raise WorkflowError("WAREHOUSE_PERMISSION_DENIED", "Scanner operator cannot access either warehouse on this transfer.", status=403)
        doc = frappe.get_doc("Warehouse Transfer", name)
        if doc.docstatus != 1 or doc.transfer_status == "Received":
            raise WorkflowError("WTS_NOT_OPEN", "The transfer was received or cancelled.")
        if _wts_fingerprint(doc) != handover.source_fingerprint:
            raise WorkflowError("SOURCE_DOCUMENT_CHANGED", "Transfer has changed after Checker verification. Ask Checker to review again.")
        from qcmc_logic.warehouse_transfer_allocation import linked_allocations
        allocations = linked_allocations(name)
        return {
            "success": True,
            "warehouse_transfer": name,
            "batch_id": handover.name,
            "checker": frappe.db.get_value("Assign Checker", handover.checker, "checker_name"),
            "status": handover.status,
            "source_warehouse": doc.source_warehouse,
            "target_warehouse": doc.target_warehouse,
            "existing_allocations": [
                {
                    "name": allocation.name,
                    "status": allocation.status,
                    "warehouse": allocation.warehouse,
                    "rows": [
                        {
                            "allocation_id": row.allocation_id,
                            "source_row": row.source_row,
                            "item_code": row.item_code,
                            "stock_uom": row.stock_uom,
                            "quantity": float(row.suggested_qty or 0),
                            "suggested_location": row.suggested_location or "",
                            "actual_location": row.actual_location or "",
                            "status": row.status,
                        }
                        for row in allocation.locations
                    ],
                }
                for allocation in allocations
            ],
            "allocation_ready": bool(allocations and all(allocation.locations for allocation in allocations)),
        }
    except WorkflowError as exc:
        return error_response(exc)
    except Exception:
        frappe.log_error(frappe.get_traceback(), "warehouse_transfer_scanner.get_picker_context")
        return error_response(WorkflowError("ERP_VALIDATION_FAILED", "Unable to load WTS Handover."))
