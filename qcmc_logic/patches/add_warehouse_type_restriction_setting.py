import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_field


def execute():
    if not frappe.db.exists("DocType", "Stock Settings"):
        return

    if frappe.get_meta("Stock Settings").has_field(
        "custom_restrict_source_target_warehouse_type"
    ):
        return

    create_custom_field(
        "Stock Settings",
        {
            "fieldname": "custom_restrict_source_target_warehouse_type",
            "label": "Restrict Source and Target Warehouse Type",
            "fieldtype": "Check",
            "default": "0",
            "insert_after": "custom_enable_global_warehouse_access",
            "description": (
                "Require source and target warehouses to use the same Warehouse Type "
                "for Material Request and Stock Entry."
            ),
        },
        ignore_validate=True,
    )

    frappe.clear_cache(doctype="Stock Settings")
