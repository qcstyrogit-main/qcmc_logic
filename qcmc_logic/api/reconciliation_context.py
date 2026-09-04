import frappe

from qcmc_logic.api.stock_reconciliation import _authenticate_request_user
from qcmc_logic.utils import ensure_scanner_warehouse_access


@frappe.whitelist(allow_guest=True)
def get_reconciliation_context(reconciliation_id=None, mobile_token=None):
    user = _authenticate_request_user(mobile_token)
    if user == "Guest" or not user:
        frappe.local.response["http_status_code"] = 401
        return {"success": False, "message": "Session expired. Please log in again."}

    reconciliation_id = str(reconciliation_id or "").strip()
    if not reconciliation_id:
        frappe.local.response["http_status_code"] = 400
        return {"success": False, "message": "Reconciliation ID is required."}

    reconciliation = frappe.db.get_value(
        "Stock Reconciliation",
        reconciliation_id,
        ["name", "docstatus", "workflow_state", "set_warehouse", "purpose"],
        as_dict=True,
    )
    if not reconciliation:
        frappe.local.response["http_status_code"] = 404
        return {
            "success": False,
            "message": f"Stock Reconciliation '{reconciliation_id}' was not found.",
        }

    if reconciliation.workflow_state in {"For Recon", "Close Inventory"}:
        frappe.local.response["http_status_code"] = 409
        return {
            "success": False,
            "error_code": "PCOUNT_NOT_OPEN",
            "message": (
                f"Stock Reconciliation '{reconciliation_id}' is already "
                f"{reconciliation.workflow_state} and is no longer available for scanning."
            ),
            "reconciliation_id": reconciliation.name,
            "workflow_state": reconciliation.workflow_state,
            "remove_from_last_activity": True,
        }

    if reconciliation.docstatus != 0:
        frappe.local.response["http_status_code"] = 400
        return {
            "success": False,
            "error_code": "PCOUNT_NOT_OPEN",
            "message": f"Stock Reconciliation '{reconciliation_id}' is not in Draft status.",
            "reconciliation_id": reconciliation.name,
            "remove_from_last_activity": True,
        }

    if not reconciliation.set_warehouse:
        frappe.local.response["http_status_code"] = 400
        return {
            "success": False,
            "message": (
                f"Stock Reconciliation '{reconciliation_id}' has no Default Warehouse. "
                "Set it in ERP before scanning."
            ),
        }

    try:
        ensure_scanner_warehouse_access(user, [reconciliation.set_warehouse])
    except frappe.PermissionError:
        frappe.local.response["http_status_code"] = 403
        return {
            "success": False,
            "error_code": "PERMISSION_DENIED",
            "message": f"You do not have scanner access to Warehouse '{reconciliation.set_warehouse}'.",
        }

    return {
        "success": True,
        "reconciliation_id": reconciliation.name,
        "warehouse": reconciliation.set_warehouse,
        "purpose": reconciliation.purpose,
    }
