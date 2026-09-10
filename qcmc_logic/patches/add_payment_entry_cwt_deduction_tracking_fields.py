import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
    create_custom_fields(
        {
            "Company": [
                {
                    "fieldname": "custom_default_cwt_account",
                    "label": "Default Creditable Withholding Tax Account",
                    "fieldtype": "Link",
                    "options": "Account",
                    "insert_after": "custom_default_ewt_payable_account",
                    "link_filters": (
                        '[["Account", "company", "=", "eval:doc.name"], '
                        '["Account", "is_group", "=", 0]]'
                    ),
                },
            ],
            "Payment Entry Deduction": [
                {
                    "fieldname": "custom_cwt_sales_invoice",
                    "label": "CWT Sales Invoice",
                    "fieldtype": "Link",
                    "options": "Sales Invoice",
                    "insert_after": "description",
                    "hidden": 1,
                    "read_only": 1,
                    "no_copy": 1,
                },
                {
                    "fieldname": "custom_cwt_allocated_amount",
                    "label": "CWT Allocated Amount",
                    "fieldtype": "Currency",
                    "insert_after": "custom_cwt_sales_invoice",
                    "hidden": 1,
                    "read_only": 1,
                    "no_copy": 1,
                },
            ],
        },
        ignore_validate=True,
    )

    frappe.clear_cache(doctype="Company")
    frappe.clear_cache(doctype="Payment Entry")
    frappe.clear_cache(doctype="Payment Entry Deduction")
