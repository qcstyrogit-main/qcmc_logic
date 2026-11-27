"""Install the schedule link before endorsement and workflow migration use it."""
import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
    if not frappe.db.has_column("Delivery Note Item", "custom_so_delivery_schedule"):
        create_custom_fields({"Delivery Note Item": [{
            "fieldname": "custom_so_delivery_schedule",
            "label": "SO Delivery Schedule",
            "fieldtype": "Link",
            "options": "SO Delivery Schedule",
            "insert_after": "so_detail",
            "read_only": 1,
            "no_copy": 1,
            "search_index": 1,
            "description": "Operational delivery schedule allocation; standard Sales Order references remain authoritative.",
        }]}, update=False)
    if not frappe.db.has_column("Delivery Note Item", "custom_so_delivery_schedule"):
        frappe.throw("Delivery Note Item schedule link was not installed. Check schema before continuing.")
