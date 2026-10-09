import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_field


STOCK_SETTINGS_FIELDS = {
    "custom_enable_global_warehouse_access": {
        "fieldname": "custom_enable_global_warehouse_access",
        "label": "Enable Global Warehouse Access",
        "fieldtype": "Check",
        "insert_after": "default_warehouse",
        "description": (
            "Apply Warehouse Access filters and single-warehouse defaults globally "
            "to doctypes with Warehouse fields."
        ),
    },
    "custom_restrict_source_target_warehouse_type": {
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
    "custom_default_actual_weight_uom": {
        "fieldname": "custom_default_actual_weight_uom",
        "label": "Default Actual Weight UOM",
        "fieldtype": "Link",
        "options": "UOM",
        "insert_after": "custom_restrict_source_target_warehouse_type",
        "description": (
            "Default UOM applied to Actual Wt/Item on finished item rows in "
            "Manufacture Stock Entries."
        ),
    },
}


MISPLACED_FIELDS = {
    "Subcontracting Receipt Item": (
        "custom_enable_global_warehouse_access",
        "custom_restrict_source_target_warehouse_type",
    ),
    "Subcontracting Receipt Supplied Item": (
        "custom_default_actual_weight_uom",
    ),
}


def execute():
    for doctype, fieldnames in MISPLACED_FIELDS.items():
        if not frappe.db.exists("DocType", doctype):
            continue

        for fieldname in fieldnames:
            field = frappe.db.exists(
                "Custom Field",
                {
                    "dt": doctype,
                    "fieldname": fieldname,
                },
            )
            if field:
                frappe.delete_doc(
                    "Custom Field",
                    field,
                    ignore_permissions=True,
                    force=True,
                )

        frappe.clear_cache(doctype=doctype)

    if not frappe.db.exists("DocType", "Stock Settings"):
        return

    stock_settings_meta = frappe.get_meta("Stock Settings")
    for fieldname, definition in STOCK_SETTINGS_FIELDS.items():
        # Legacy fixtures can leave this primary key with a different dt or
        # fieldname. create_custom_field checks dt/fieldname, so it would try to
        # insert the same primary key again instead of repairing that record.
        canonical_name = f"Stock Settings-{fieldname}"
        if frappe.db.exists("Custom Field", canonical_name):
            field = frappe.get_doc("Custom Field", canonical_name)
            if field.dt != "Stock Settings" or field.fieldname != fieldname:
                old_doctype = field.dt
                field.update({**definition, "dt": "Stock Settings"})
                field.flags.ignore_validate = True
                field.save(ignore_permissions=True)
                if old_doctype:
                    frappe.clear_cache(doctype=old_doctype)
            continue

        if frappe.db.exists("Custom Field", {"dt": "Stock Settings", "fieldname": fieldname}):
            continue

        if not stock_settings_meta.has_field(fieldname):
            create_custom_field(
                "Stock Settings",
                definition,
                ignore_validate=True,
            )
            stock_settings_meta = frappe.get_meta("Stock Settings")

    frappe.clear_cache(doctype="Stock Settings")
