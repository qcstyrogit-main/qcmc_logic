import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
    create_custom_fields(
        {
            "Company": [
                {
                    "fieldname": "custom_default_cwt_rate",
                    "label": "Default CWT Rate",
                    "fieldtype": "Percent",
                    "insert_after": "custom_default_cwt_account",
                    "default": "1",
                    "description": "Used when the Customer has no CWT Rate configured.",
                },
                {
                    "fieldname": "custom_default_cwt_vat_rate",
                    "label": "Default CWT VAT Rate",
                    "fieldtype": "Percent",
                    "insert_after": "custom_default_cwt_rate",
                    "default": "12",
                    "description": "Used to derive the VAT-exclusive base for suggested CWT amounts.",
                },
            ],
            "Customer": [
                {
                    "fieldname": "custom_cwt_rate",
                    "label": "CWT Rate",
                    "fieldtype": "Percent",
                    "insert_after": "tax_withholding_category",
                    "description": "Overrides the Company default CWT rate when greater than zero.",
                },
            ],
            "Payment Entry Deduction": [
                {
                    "fieldname": "custom_cwt_rate",
                    "label": "CWT Rate",
                    "fieldtype": "Percent",
                    "insert_after": "custom_cwt_allocated_amount",
                    "hidden": 1,
                    "read_only": 1,
                    "no_copy": 1,
                },
                {
                    "fieldname": "custom_cwt_vat_rate",
                    "label": "CWT VAT Rate",
                    "fieldtype": "Percent",
                    "insert_after": "custom_cwt_rate",
                    "hidden": 1,
                    "read_only": 1,
                    "no_copy": 1,
                },
            ],
        },
        ignore_validate=True,
    )

    for company in frappe.get_all(
        "Company",
        fields=["name", "custom_default_cwt_rate", "custom_default_cwt_vat_rate"],
    ):
        updates = {}
        if not company.custom_default_cwt_rate:
            updates["custom_default_cwt_rate"] = 1
        if not company.custom_default_cwt_vat_rate:
            updates["custom_default_cwt_vat_rate"] = 12
        if updates:
            frappe.db.set_value("Company", company.name, updates, update_modified=False)

    frappe.clear_cache(doctype="Company")
    frappe.clear_cache(doctype="Customer")
    frappe.clear_cache(doctype="Payment Entry Deduction")
