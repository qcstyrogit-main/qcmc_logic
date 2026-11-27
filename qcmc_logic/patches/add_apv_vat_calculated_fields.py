"""Add reference-only computed VAT component and PV amount fields."""
import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

def execute():
    create_custom_fields({
        "Purchase Invoice VAT Detail": [
            {"fieldname": "custom_vat_inclusive", "label": "VAT Inclusive",
             "fieldtype": "Currency", "options": "parent.currency",
             "insert_after": "amount", "read_only": 1, "in_list_view": 1},
            {"fieldname": "custom_pv_amount", "label": "PV Amount",
             "fieldtype": "Currency", "options": "parent.currency",
             "insert_after": "custom_vat_inclusive", "read_only": 1,
             "in_list_view": 1},
        ]
    }, ignore_validate=True)
    frappe.clear_cache(doctype="Purchase Invoice VAT Detail")
    frappe.clear_cache(doctype="Purchase Invoice")
