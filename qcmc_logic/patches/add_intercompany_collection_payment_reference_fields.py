import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
    create_custom_fields(
        {
            "Payment Entry": [
                {
                    "fieldname": "custom_intercompany_source_payment_entry",
                    "label": "Intercompany Source Payment Entry",
                    "fieldtype": "Link",
                    "options": "Payment Entry",
                    "insert_after": "custom_ref_doc",
                    "read_only": 1,
                    "no_copy": 1,
                },
                {
                    "fieldname": "custom_intercompany_target_payment_entry",
                    "label": "Intercompany Target Payment Entry",
                    "fieldtype": "Link",
                    "options": "Payment Entry",
                    "insert_after": "custom_intercompany_source_payment_entry",
                    "read_only": 1,
                    "no_copy": 1,
                },
            ]
        },
        ignore_validate=True,
    )

    frappe.clear_cache(doctype="Payment Entry")
