"""Read-only, narrow Item catalog for authenticated QCMC Scanner devices.

No Item DocType Read permission is granted. Authentication uses the same
mobile token or ERP session as existing scanner endpoints. Warehouse access
from a user's Role Profile is required before exposing the catalog.
"""
import frappe
from frappe.utils import cint, now_datetime
from qcmc_logic.api.mobile_auth import extract_mobile_token, resolve_device_token_user
from qcmc_logic.utils import get_user_allowed_warehouses

MAX_PAGE_SIZE = 500
FG_GROUP_NAMES = ("Finished Goods", "FG")


def _get_fg_group_bounds():
    """Return FG Item Group subtrees, including descendants."""
    groups = frappe.db.sql(
        """select name, lft, rgt from `tabItem Group`
        where name in %(groups)s""",
        {"groups": FG_GROUP_NAMES}, as_dict=True,
    )
    if not groups:
        frappe.throw(
            "Finished Goods Item Group not found. Configure 'Finished Goods' or 'FG'.",
            frappe.ValidationError,
        )
    return [(int(group.lft), int(group.rgt)) for group in groups]



def _require_catalog_user(mobile_token=None):
    token = extract_mobile_token(mobile_token)
    if token:
        user = resolve_device_token_user(token)
    else:
        user = frappe.session.user
    if not user or user == "Guest":
        frappe.throw("Scanner session expired. Please log in again.", frappe.AuthenticationError)
    if not cint(frappe.db.get_value("User", user, "enabled")):
        frappe.throw("Scanner user is disabled.", frappe.PermissionError)
    if user != "Administrator" and not get_user_allowed_warehouses(
        user, require_list_view=True, source="Role Profile"
    ):
        frappe.throw("Scanner warehouse access is required to synchronize the Item catalog.", frappe.PermissionError)
    return user


def _validate_cursor(value, label):
    text = str(value or "").strip()
    if len(text) > 240:
        frappe.throw(f"{label} is too long.", frappe.ValidationError)
    return text


@frappe.whitelist(allow_guest=True, methods=["POST"])
def get_items(
    mobile_token=None,
    since_modified=None,
    cursor_modified=None,
    cursor_item_code=None,
    until_modified=None,
    limit=500,
):
    """Return Finished Goods items; delta pages include moved/disabled tombstones.

    Item Group roots 'Finished Goods' or 'FG' include their descendant groups.
    Delta pages contain tombstones for non-FG changes so previously cached FG
    items moved to another group are removed locally.
    A stable modified/name cursor avoids offset skipping when new items are
    added during a long synchronization. Clients retain their previous cache
    until the entire sequence completes successfully.
    """
    _require_catalog_user(mobile_token)
    try:
        page_size = cint(limit)
    except (TypeError, ValueError):
        page_size = 0
    if not 1 <= page_size <= MAX_PAGE_SIZE:
        frappe.throw("limit must be between 1 and 500.", frappe.ValidationError)

    since = _validate_cursor(since_modified, "since_modified")
    after_modified = _validate_cursor(cursor_modified, "cursor_modified")
    after_code = _validate_cursor(cursor_item_code, "cursor_item_code")
    if bool(after_modified) != bool(after_code):
        frappe.throw("Both cursor fields are required together.", frappe.ValidationError)

    upper = _validate_cursor(until_modified, "until_modified") or str(now_datetime())
    bounds = _get_fg_group_bounds()
    fg_clause = "(" + " or ".join(
        f"(item_group_record.lft >= %(fg_lft_{index})s and item_group_record.rgt <= %(fg_rgt_{index})s)"
        for index in range(len(bounds))
    ) + ")"
    where = ["item.modified <= %(upper)s"]
    params = {"upper": upper, "page_size": page_size + 1}
    for index, (left, right) in enumerate(bounds):
        params[f"fg_lft_{index}"] = left
        params[f"fg_rgt_{index}"] = right
    if since:
        # Include the watermark timestamp again to avoid losing ties.
        where.append("item.modified >= %(since)s")
        params["since"] = since
    else:
        where.append("item.disabled = 0")
    if after_modified:
        where.append("(item.modified > %(after_modified)s or (item.modified = %(after_modified)s and item.name > %(after_code)s))")
        params["after_modified"] = after_modified
        params["after_code"] = after_code

    rows = frappe.db.sql(
        """
        select item.name,
               case when """ + fg_clause + """ then item.item_name else '' end as item_name,
               case when """ + fg_clause + """ then item.description else '' end as description,
               case when """ + fg_clause + """ then item.stock_uom else '' end as stock_uom,
               item.modified,
               case when item.disabled = 1 or not """ + fg_clause + """ then 1 else 0 end as disabled
        from `tabItem` item
        left join `tabItem Group` item_group_record on item_group_record.name = item.item_group
        where """ + " and ".join(where) + ("" if since else " and " + fg_clause) + """
        order by item.modified asc, item.name asc
        limit %(page_size)s
        """,
        params,
        as_dict=True,
    )
    has_more = len(rows) > page_size
    rows = rows[:page_size]
    last = rows[-1] if rows else None
    return {
        "success": True,
        "items": [
            {
                "name": item.name,
                "item_name": item.item_name or "",
                "description": item.description or "",
                "stock_uom": item.stock_uom or "",
                "modified": str(item.modified),
                "disabled": cint(item.disabled),
            }
            for item in rows
        ],
        "has_more": has_more,
        "next_cursor_modified": str(last.modified) if has_more and last else "",
        "next_cursor_item_code": last.name if has_more and last else "",
        "until_modified": upper,
    }
