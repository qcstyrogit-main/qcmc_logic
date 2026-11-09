"""Read-only diagnostics for a failed QCMC Physical Count recount.

Run with:
bench --site <development-site> execute qcmc_logic.tests.recount_submission_diagnostics.inspect_recount --kwargs '{"reconciliation_id":"MAT-RECO-2026-00038","item_code":"EIEHB1BL50","inventory_location":"B4MB3L23"}'
"""
import json

import frappe


def _number(value):
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return str(value)[:80]


def inspect_recount(reconciliation_id, item_code="", inventory_location=""):
    """Return saved submission diagnostics only. No writes or resubmissions."""
    reconciliation_id = str(reconciliation_id or "").strip()
    item_code = str(item_code or "").strip()
    inventory_location = str(inventory_location or "").strip()
    if not reconciliation_id:
        raise ValueError("reconciliation_id is required")
    if not frappe.db.exists("Stock Reconciliation", reconciliation_id):
        return {"error": "Reconciliation not found", "reconciliation_id": reconciliation_id}

    document = frappe.get_doc("Stock Reconciliation", reconciliation_id)
    submissions = frappe.get_all(
        "Physical Count Submission",
        filters={"reconciliation": reconciliation_id},
        fields=[
            "name", "submission_id", "status", "error_code", "error_message",
            "received_at", "processed_at", "request_json"
        ],
        order_by="creation desc",
        limit_page_length=12,
    )

    matching = []
    for submission in submissions:
        try:
            payload = json.loads(submission.request_json or "{}")
            rows = payload.get("entries") or []
        except (TypeError, ValueError, AttributeError):
            rows = []
        summaries = []
        for entry in rows:
            if not isinstance(entry, dict):
                continue
            code = str(entry.get("itemCode") or entry.get("item_code") or "")
            location = str(entry.get("inventoryLocation") or entry.get("inventory_location") or "")
            if item_code and code != item_code:
                continue
            if inventory_location and location != inventory_location:
                continue
            transactions = entry.get("transactions") or []
            summaries.append({
                "item_code": code,
                "inventory_location": location,
                "warehouse": entry.get("warehouse"),
                "expected_erp_quantity": _number(entry.get("expectedERPQuantity", entry.get("expected_erp_quantity"))),
                "expected_previous_count": _number(entry.get("expectedPreviousCount", entry.get("expected_previous_count"))),
                "physical_count": _number(entry.get("physicalCount", entry.get("physical_count"))),
                "quantity_delta": _number(entry.get("quantityDelta", entry.get("quantity_delta"))),
                "transactions": len(transactions) if isinstance(transactions, list) else None,
            })
        if not summaries and (item_code or inventory_location):
            continue
        matching.append({
            "submission_id": submission.submission_id or submission.name,
            "status": submission.status,
            "error_code": submission.error_code or "",
            "error_message": str(submission.error_message or "")[:1800],
            "received_at": str(submission.received_at or ""),
            "processed_at": str(submission.processed_at or ""),
            "entries": summaries,
        })

    saved_rows = []
    for row in document.get("custom_physical_count_results") or []:
        code = str(row.item_code or "")
        location = str(row.get("location") or row.get("inventory_location") or "")
        if item_code and code != item_code:
            continue
        if inventory_location and location != inventory_location:
            continue
        saved_rows.append({
            "item_code": code,
            "inventory_location": location,
            "inventory_tag": str(row.get("inventory_tag") or ""),
            "submission_id": row.get("submission_id"),
            "physical_count": _number(row.get("physical_count")),
            "erp_quantity_before": _number(row.get("erp_quantity_before")),
            "quantity_delta": _number(row.get("quantity_delta")),
            "status": row.get("status"),
        })

    return {
        "reconciliation_id": reconciliation_id,
        "docstatus": document.docstatus,
        "workflow_state": document.get("workflow_state"),
        "warehouse": document.get("set_warehouse"),
        "recent_matching_submissions": matching,
        "saved_count_rows": saved_rows[:40],
        "note": "Read-only; does not alter submission status, stock, or audit records.",
    }
