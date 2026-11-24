"""Add reference-only VAT details to Purchase Invoice (Accounts Payable Voucher).

These custom fields are not part of the taxes, totals or GL posting pipelines.
"""
import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


CHILD_DOCTYPE = "Purchase Invoice VAT Detail"


def execute():
    if not frappe.db.exists("DocType", CHILD_DOCTYPE):
        frappe.get_doc({
            "doctype": "DocType",
            "name": CHILD_DOCTYPE,
            "module": "QCMC Logics",
            "custom": 1,
            "istable": 1,
            "editable_grid": 1,
            "fields": [
                {
                    "fieldname": "account_name",
                    "fieldtype": "Link",
                    "label": "Account Name",
                    "options": "Account",
                    "reqd": 1,
                    "in_list_view": 1,
                    "columns": 5,
                },
                {
                    "fieldname": "cost_center",
                    "fieldtype": "Link",
                    "label": "Cost Center",
                    "options": "Cost Center",
                    "in_list_view": 1,
                    "columns": 3,
                },
                {
                    "fieldname": "amount",
                    "fieldtype": "Currency",
                    "label": "Amount",
                    "options": "parent.currency",
                    "reqd": 1,
                    "in_list_view": 1,
                    "columns": 2,
                },
            ],
        }).insert(ignore_permissions=True)

    create_custom_fields({
        CHILD_DOCTYPE: [{
            "fieldname": "cost_center",
            "fieldtype": "Link",
            "label": "Cost Center",
            "options": "Cost Center",
            "insert_after": "account_name",
            "in_list_view": 1,
        }],
        "Purchase Invoice": [
            {
                "fieldname": "custom_show_vat_details",
                "fieldtype": "Check",
                "label": "VAT Details",
                "default": "0",
                "insert_after": "scan_barcode",
                "print_hide": 1,
            },
            {
                "fieldname": "custom_vat_details",
                "fieldtype": "Table",
                "label": "VAT Details",
                "options": CHILD_DOCTYPE,
                "insert_after": "custom_show_vat_details",
                "depends_on": "eval:doc.custom_show_vat_details == 1",
                "print_hide": 1,
            },
        ],
    }, ignore_validate=True)

    frappe.clear_cache(doctype=CHILD_DOCTYPE)
    frappe.clear_cache(doctype="Purchase Invoice")
