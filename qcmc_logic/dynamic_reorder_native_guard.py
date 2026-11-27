"""Fail-closed safeguard for native ERPNext auto-reorder requests.

This is defense in depth, not authorization to apply consolidated reorder values.
Manual material requests are not affected.
"""
import frappe


def protected_pairs(doc):
    if not doc.get("auto_created_via_reorder"):
        return set()
    if not frappe.get_meta("Item Reorder").has_field("custom_managed_reorder"):
        return set()
    items = sorted({row.item_code for row in doc.get("items") or [] if row.item_code})
    if not items:
        return set()
    # Lock the same item records that a future approval transaction must lock.
    placeholders = ", ".join(["%s"] * len(items))
    frappe.db.sql(
        "SELECT name FROM tabItem WHERE name IN (" + placeholders + ") ORDER BY name FOR UPDATE",
        tuple(items),
    )
    managed = frappe.db.sql(
        """SELECT parent, warehouse FROM `tabItem Reorder`
           WHERE parent IN (""" + placeholders + """)
             AND parenttype='Item' AND parentfield='reorder_levels'
             AND custom_managed_reorder=1 FOR UPDATE""",
        tuple(items), as_dict=True,
    )
    return {(row.parent, row.warehouse) for row in managed}


def filter_new_native_request(doc, method=None):
    """Remove only managed item/destination pairs before a new native MR is inserted."""
    protected = protected_pairs(doc)
    rows = doc.get("items") or []
    remaining = [r for r in rows if (r.item_code, r.warehouse) not in protected]
    if len(remaining) == len(rows):
        return
    if not remaining:
        frappe.throw("Native auto-reorder has no unmanaged items to request")
    doc.set("items", remaining)
    doc.schedule_date = max(r.schedule_date for r in remaining)


def validate_native_request(doc, method=None):
    protected = protected_pairs(doc)
    conflicts = sorted({(row.item_code, row.warehouse) for row in doc.get("items") or []
                        if (row.item_code, row.warehouse) in protected})
    if conflicts:
        frappe.throw("Native auto-reorder request blocked for managed item/warehouse: " +
                     ", ".join(item + " / " + warehouse for item, warehouse in conflicts))
