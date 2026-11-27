"""Retain historic values but retire obsolete scheduling fields from Delivery Note UI."""
import frappe

FIELDS = (
    "custom_logistics_reason", "custom_logistics_remarks",
    "custom_logistics_proposed_qty", "custom_logistics_proposed_date",
    "custom_sales_final_qty", "custom_sales_move_date", "custom_sales_remove",
)


def execute():
    # Runs after fixture sync so old fixture definitions cannot re-expose fields.
    for fieldname in FIELDS:
        name = frappe.db.get_value("Custom Field", {"dt": "Delivery Note Item", "fieldname": fieldname}, "name")
        if name:
            frappe.db.set_value("Custom Field", name, {
                "hidden": 1, "read_only": 1, "in_list_view": 0,
            }, update_modified=False)
    frappe.clear_cache(doctype="Delivery Note Item")
    frappe.clear_cache(doctype="Delivery Note")
