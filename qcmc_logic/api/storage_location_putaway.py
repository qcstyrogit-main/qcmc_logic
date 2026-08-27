import frappe
from frappe import _

from qcmc_logic.api.stock_reconciliation import (
    _authenticate_request_user,
)

from qcmc_logic.qcmc_logics.doctype.storage_location.storage_location import (
    get_putaway_distribution as _get_putaway_distribution,
)
from qcmc_logic.utils import ensure_scanner_warehouse_access


@frappe.whitelist(allow_guest=True)
def get_putaway_distribution(
    storage_location=None,
    item_code=None,
    quantity=None,
    mobile_token=None,
    reconciliation_id=None,
):
    # Authenticate using the same mobile token as your
    # existing Stock Reconciliation scanner API.
    user = _authenticate_request_user(mobile_token)

    if not user:
        frappe.throw(
            _("Authentication failed."),
            frappe.AuthenticationError,
        )

    if not storage_location:
        frappe.throw(_("Storage Location is required."))

    if not item_code:
        frappe.throw(_("Scanned Item Code is required."))

    if quantity is None:
        frappe.throw(_("Quantity is required."))

    reconciliation_id = reconciliation_id or frappe.form_dict.get("reconciliation_id")
    reconciliation = None
    if reconciliation_id:
        reconciliation = frappe.db.get_value(
            "Stock Reconciliation",
            {"name": reconciliation_id, "docstatus": 0},
            ["company", "set_warehouse"],
            as_dict=True,
        )
    if not reconciliation:
        reconciliation = frappe.db.get_value(
            "Stock Reconciliation",
            {"owner": user, "docstatus": 0, "set_warehouse": ["is", "set"]},
            ["company", "set_warehouse"],
            order_by="modified desc",
            as_dict=True,
        )

    warehouse = reconciliation.get("set_warehouse") if reconciliation else None
    if not warehouse:
        warehouse = frappe.db.get_value(
            "Storage Location", storage_location, "custom_warehouse"
        )
    ensure_scanner_warehouse_access(user, [warehouse])
    if not reconciliation:
        # Some scanner references are created by Administrator on behalf of
        # the mobile user. In that case ownership cannot identify the active
        # reference; use the most recently modified warehouse-bound draft.
        reconciliation = frappe.db.get_value(
            "Stock Reconciliation",
            {"docstatus": 0, "set_warehouse": ["is", "set"]},
            ["company", "set_warehouse"],
            order_by="modified desc",
            as_dict=True,
        )

    # Return business validation as a normal API response so mobile scanners
    # can show the useful capacity/location message instead of a generic 417.
    try:
        return _get_putaway_distribution(
            storage_location=storage_location,
            item_code=item_code,
            quantity=quantity,
            company=reconciliation.get("company") if reconciliation else None,
            warehouse=warehouse,
        )
    except frappe.ValidationError as exc:
        return {
            "success": False,
            "message": str(exc),
            "storage_location": storage_location,
            "item_code": item_code,
            "requested_quantity": quantity,
        }
