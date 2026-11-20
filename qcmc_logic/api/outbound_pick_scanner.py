"""Scanner verification of existing Material Issue and Delivery Note Pick Lists.

This module does not submit Stock Entries, Delivery Notes or Stock Ledger Entries.
An operator may only confirm physically scanned, complete picking for an existing
draft Pick List. ERPNext document submission/approval remains a separate action.
"""
import re
from decimal import Decimal, InvalidOperation

import frappe

from qcmc_logic.api.warehouse_workflow import (
    WorkflowError, authenticated_user, error_response, parse_json,
)
from qcmc_logic.utils import ensure_scanner_warehouse_access

KINDS = {
    "material_issue": ("Stock Entry", "Material Issue"),
    "delivery_note": ("Delivery Note", "Delivery"),
}


def _reference(value):
    name = str(value or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,139}", name):
        raise WorkflowError("INVALID_REFERENCE", "Scan the exact ERPNext document reference.")
    return name


def _context(kind, reference, user):
    if kind not in KINDS:
        raise WorkflowError("INVALID_TYPE", "Choose Material Issue or Delivery Note.")
    doctype, purpose = KINDS[kind]
    doc = frappe.get_doc(doctype, _reference(reference))
    doc.check_permission("read")
    if kind == "material_issue":
        if doc.stock_entry_type != "Material Issue" or doc.purpose != "Material Issue":
            raise WorkflowError("WRONG_TRANSACTION_TYPE", "This Stock Entry is not a Material Issue.")
        names = [str(doc.pick_list)] if doc.pick_list else []
    else:
        if doc.get("is_return"):
            raise WorkflowError("RETURN_NOT_SUPPORTED", "Delivery returns require a separate IN workflow.")
        names = sorted({row.against_pick_list for row in doc.items if row.against_pick_list})
    if doc.docstatus != 0:
        raise WorkflowError("DOCUMENT_NOT_DRAFT", "Only draft source documents can be picked on this scanner.")
    if not names:
        raise WorkflowError("PICK_LIST_REQUIRED", "Create and save the Pick List in ERPNext first.")
    if len(names) != 1:
        raise WorkflowError("MULTIPLE_PICK_LISTS", "This document has multiple Pick Lists. Review it in ERPNext.")
    pick = frappe.get_doc("Pick List", names[0])
    pick.check_permission("read")
    if pick.company != doc.company or pick.purpose != purpose or pick.docstatus == 2:
        raise WorkflowError("PICK_LIST_MISMATCH", "The linked Pick List is cancelled or belongs to a different transaction.")
    if not pick.locations:
        raise WorkflowError("NO_PICK_ROWS", "Linked Pick List has no rows.")
    warehouses = sorted({row.warehouse for row in pick.locations if row.warehouse})
    if not warehouses or any(not row.warehouse for row in pick.locations):
        raise WorkflowError("WAREHOUSE_REQUIRED", "Every Pick List row needs a source Warehouse.")
    ensure_scanner_warehouse_access(user, warehouses, require_transact=False)
    return doc, pick


def _rows(pick):
    return [{
        "row_id": row.name,
        "item_code": row.item_code,
        "item_name": frappe.get_cached_value("Item", row.item_code, "item_name") or row.item_code,
        "warehouse": row.warehouse,
        "location": row.location or "",
        "stock_uom": row.stock_uom or row.uom or "",
        "required_qty": float(row.stock_qty or 0),
        "picked_qty": float(row.picked_qty or 0),
        "delivered_qty": float(row.delivered_qty or 0),
    } for row in pick.locations]


@frappe.whitelist(allow_guest=True, methods=["POST"])
def get_context(kind, reference, mobile_token=None):
    try:
        user = authenticated_user(mobile_token)
        doc, pick = _context(str(kind or ""), reference, user)
        return {
            "success": True, "kind": kind, "reference": doc.name,
            "document_type": doc.doctype, "pick_list": pick.name,
            "pick_docstatus": pick.docstatus,
            "rows": _rows(pick),
            "source_status": doc.workflow_state if doc.meta.has_field("workflow_state") else "Draft",
            "can_confirm_pick": pick.docstatus == 0,
        }
    except WorkflowError as exc:
        return error_response(exc)
    except frappe.PermissionError:
        return error_response(WorkflowError("PERMISSION_DENIED", "You cannot access this transaction.", status=403))
    except frappe.DoesNotExistError:
        return error_response(WorkflowError("DOCUMENT_NOT_FOUND", "The document or Pick List was not found.", status=404))


def _positive_decimal(value):
    try:
        quantity = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise WorkflowError("INVALID_QUANTITY", "Scanned quantity is not a valid number.")
    if not quantity.is_finite() or quantity <= 0:
        raise WorkflowError("INVALID_QUANTITY", "Scanned quantity must be greater than zero.")
    return quantity


@frappe.whitelist(allow_guest=True, methods=["POST"])
def submit_verified_pick(kind, reference, picked_rows, mobile_token=None):
    """Submit only the linked draft Pick List, never its commercial/stock source.

    A row must have the exact scanned source location and full picked quantity.
    The source and Pick List are locked so concurrent picking cannot silently
    overwrite a second operator's data.
    """
    try:
        user = authenticated_user(mobile_token)
        doctype = KINDS.get(str(kind or ""), ("", ""))[0]
        if not doctype:
            raise WorkflowError("INVALID_TYPE", "Choose Material Issue or Delivery Note.")
        name = _reference(reference)
        frappe.db.sql("select name from `tab%s` where name=%%s for update" % doctype, (name,))
        doc, pick = _context(str(kind or ""), name, user)
        frappe.db.sql("select name from `tabPick List` where name=%s for update", (pick.name,))
        doc, pick = _context(str(kind or ""), name, user)
        if pick.docstatus != 0:
            raise WorkflowError("ALREADY_SUBMITTED", "Pick List is not a draft. Refresh the document in ERPNext.")
        pick.check_permission("submit")
        pick.check_permission("write")
        warehouses = sorted({row.warehouse for row in pick.locations})
        ensure_scanner_warehouse_access(user, warehouses, require_transact=True)
        provided = parse_json(picked_rows, [])
        if not isinstance(provided, list) or len(provided) != len(pick.locations):
            raise WorkflowError("INCOMPLETE_PICK", "Physically verify every Pick List row.")
        scanned = {}
        for value in provided:
            if not isinstance(value, dict):
                raise WorkflowError("INVALID_PICK", "Pick List verification rows must be objects.")
            key = str(value.get("row_id") or "").strip()
            if not key or key in scanned:
                raise WorkflowError("DUPLICATE_PICK", "A Pick List row was scanned twice or has no ID.")
            scanned[key] = value
        if set(scanned) != {row.name for row in pick.locations}:
            raise WorkflowError("PICK_LIST_CHANGED", "Pick List rows changed. Reload and scan again.")
        for row in pick.locations:
            scanned_row = scanned[row.name]
            location_id = _reference(scanned_row.get("location"))
            if not row.location or row.location != location_id:
                raise WorkflowError("LOCATION_MISMATCH", "Scan the exact assigned Storage Location for " + row.item_code)
            location = frappe.db.get_value("Storage Location", location_id,
                ["custom_warehouse", "disabled", "is_group"], as_dict=True)
            if not location or location.disabled or location.is_group or location.custom_warehouse != row.warehouse:
                raise WorkflowError("INVALID_LOCATION", "This Storage Location is not an enabled leaf of the source Warehouse.")
            actual = _positive_decimal(scanned_row.get("quantity"))
            expected = _positive_decimal(row.stock_qty)
            if abs(actual - expected) > Decimal("0.000001"):
                raise WorkflowError("QUANTITY_MISMATCH", "Picked quantity for " + row.item_code + " must match the Pick List. Correct shortages in ERPNext first.")
            row.picked_qty = float(actual)
        pick.save()
        pick.submit()
        # Validate the source against the submitted pick before committing.
        # Exceptions roll back the whole Frappe request, including pick.submit().
        if kind == "material_issue":
            from qcmc_logic.stock_entry_material_issue_pick_list import validate_material_issue_picking
            validate_material_issue_picking(doc)
        else:
            from qcmc_logic.delivery_note_pick_list import validate_delivery_pick_list_ready
            validate_delivery_pick_list_ready(doc)
        # Do not submit the Stock Entry or Delivery Note: preserve Desk approval.
        return {"success": True, "reference": doc.name, "pick_list": pick.name,
                "pick_docstatus": pick.docstatus, "source_submitted": False,
                "verified_rows": len(pick.locations)}
    except WorkflowError as exc:
        return error_response(exc)
    except frappe.PermissionError:
        return error_response(WorkflowError("PERMISSION_DENIED", "You cannot submit this Pick List.", status=403))
    except frappe.DoesNotExistError:
        return error_response(WorkflowError("DOCUMENT_NOT_FOUND", "Source document or Pick List was not found.", status=404))

@frappe.whitelist(allow_guest=True, methods=["POST"])
def list_available_documents(kind, search="", mobile_token=None):
    """Browse operator-visible draft source documents including pending preparation.

    A Delivery Note with a submitted Pick List is intentionally visible as
    'picked', not silently hidden. Items without a Pick List are shown with
    their next ERPNext action. This is read-only and enforces warehouse access.
    """
    try:
        user = authenticated_user(mobile_token)
        kind = str(kind or "").strip()
        if kind not in KINDS:
            raise WorkflowError("INVALID_TYPE", "Choose Material Issue or Delivery Note.")
        doctype, purpose = KINDS[kind]
        query = str(search or "").strip()
        if len(query) > 100:
            raise WorkflowError("INVALID_SEARCH", "Search is too long.")
        filters = {"docstatus": 0}
        if kind == "material_issue":
            filters.update({"stock_entry_type": "Material Issue", "purpose": "Material Issue"})
        else:
            filters["is_return"] = 0
        if query:
            if kind == "delivery_note":
                # Accept an exact Pick List ID as a lookup key as well as
                # Delivery Note IDs. The parent query still applies user
                # permissions and the warehouse access checks below.
                linked_notes = frappe.get_all("Delivery Note Item",
                    filters={"against_pick_list": query},
                    pluck="parent", limit_page_length=500)
                if linked_notes:
                    filters["name"] = ["in", sorted(set(linked_notes))]
                else:
                    filters["name"] = ["like", "%" + query.replace("%", r"\\%").replace("_", r"\\_") + "%"]
            else:
                filters["name"] = ["like", "%" + query.replace("%", r"\\%").replace("_", r"\\_") + "%"]
        # get_list applies Frappe permission_query_conditions for this user.
        candidates = frappe.get_list(doctype, filters=filters,
            fields=["name", "company", "modified"],
            order_by="modified desc", limit_page_length=150)
        documents = []
        for candidate in candidates:
            try:
                doc = frappe.get_doc(doctype, candidate.name)
                doc.check_permission("read")
                if kind == "material_issue":
                    names = [doc.pick_list] if doc.pick_list else []
                    warehouses = {row.s_warehouse for row in doc.items if row.s_warehouse}
                else:
                    names = sorted({row.against_pick_list for row in doc.items if row.against_pick_list})
                    warehouses = {row.warehouse for row in doc.items if row.warehouse}
                # Do not list inaccessible documents based solely on DocType access.
                if not warehouses:
                    continue
                ensure_scanner_warehouse_access(user, sorted(warehouses), require_transact=False)
                pick = None
                state = "setup_required"
                hint = "Create a Pick List in ERPNext before scanning."
                rows = []
                if len(names) > 1:
                    state = "review_required"
                    hint = "Multiple Pick Lists are linked. Review in ERPNext."
                elif len(names) == 1:
                    pick = frappe.get_doc("Pick List", names[0])
                    pick.check_permission("read")
                    if pick.company != doc.company or pick.purpose != purpose or pick.docstatus == 2:
                        state = "review_required"
                        hint = "Linked Pick List is invalid or cancelled. Review in ERPNext."
                    else:
                        pick_warehouses = {row.warehouse for row in pick.locations if row.warehouse}
                        ensure_scanner_warehouse_access(user, sorted(pick_warehouses), require_transact=False)
                        rows = list(pick.locations)
                        if pick.docstatus == 1:
                            state, hint = "picked", "Pick List submitted. Continue in ERPNext."
                        elif any(not row.location or float(row.stock_qty or 0) <= 0 for row in rows):
                            state, hint = "needs_location", "Assign source Storage Locations in ERPNext."
                        else:
                            state, hint = "scan_ready", "Ready to scan and verify."
                documents.append({
                    "reference": doc.name, "company": doc.company,
                    "modified": str(candidate.modified or ""),
                    "status": (doc.workflow_state if doc.meta.has_field("workflow_state") else "Draft") or "Draft",
                    "pick_list": pick.name if pick else "",
                    "warehouse": ", ".join(sorted(warehouses)),
                    "item_count": len(rows), "ready": state == "scan_ready",
                    "state": state, "hint": hint,
                })
            except (WorkflowError, frappe.PermissionError, frappe.DoesNotExistError):
                continue
        order = {"scan_ready": 0, "needs_location": 1, "picked": 2,
                 "setup_required": 3, "review_required": 4}
        documents.sort(key=lambda d: (order.get(d["state"], 9), d["modified"]), reverse=False)
        # Keep most recently modified documents first within each priority group.
        from itertools import groupby
        documents = [doc for _, group in groupby(documents, lambda d: order.get(d["state"], 9))
                     for doc in sorted(group, key=lambda d: d["modified"], reverse=True)]
        return {"success": True, "documents": documents[:80]}
    except WorkflowError as exc:
        return error_response(exc)
    except frappe.PermissionError:
        return error_response(WorkflowError("PERMISSION_DENIED", "You cannot list these transactions.", status=403))
    except Exception:
        frappe.log_error(frappe.get_traceback(), "outbound_pick_scanner.list_available_documents")
        return error_response(WorkflowError("ERP_VALIDATION_FAILED", "Unable to list pending transactions."))


