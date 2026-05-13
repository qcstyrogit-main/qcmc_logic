import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_field


def execute():
    ensure_warehouse_transfer_location_fields()
    ensure_stock_ledger_location_field()

    for doctype in ("Warehouse Transfer", "Stock Ledger Entry"):
        frappe.clear_cache(doctype=doctype)


def ensure_warehouse_transfer_location_fields():
    if not frappe.db.exists("DocType", "Warehouse Transfer"):
        return

    meta = frappe.get_meta("Warehouse Transfer", cached=False)
    fields = (
        {
            "fieldname": "source_location",
            "label": "Source Location",
            "insert_after": "source_company",
        },
        {
            "fieldname": "target_location",
            "label": "Target Location",
            "insert_after": "target_warehouse",
        },
    )

    for field in fields:
        if meta.has_field(field["fieldname"]) or frappe.db.exists(
            "Custom Field",
            {"dt": "Warehouse Transfer", "fieldname": field["fieldname"]},
        ):
            continue

        create_custom_field(
            "Warehouse Transfer",
            {
                **field,
                "fieldtype": "Link",
                "options": "Location",
                "read_only": 1,
                "allow_on_submit": 1,
            },
            ignore_validate=True,
        )


def ensure_stock_ledger_location_field():
    has_location = frappe.get_meta("Stock Ledger Entry", cached=False).has_field("location")
    if has_location or frappe.db.exists(
        "Custom Field",
        {"dt": "Stock Ledger Entry", "fieldname": "location"},
    ):
        return

    create_custom_field(
        "Stock Ledger Entry",
        {
            "fieldname": "location",
            "label": "Location",
            "fieldtype": "Link",
            "options": "Location",
            "insert_after": "warehouse",
            "read_only": 1,
            "allow_on_submit": 1,
        },
        ignore_validate=True,
    )
