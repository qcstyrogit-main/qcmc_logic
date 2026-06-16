import frappe


def execute():
    doc = frappe.get_doc("DocType", "Allowed Warehouse")

    doc.module = "Stock"
    doc.custom = 1
    doc.istable = 1
    doc.editable_grid = 1
    doc.title_field = ""
    doc.permissions = []
    doc.fields = []

    doc.append(
        "fields",
        {
            "fieldname": "warehouse",
            "label": "Warehouse",
            "fieldtype": "Link",
            "options": "Warehouse",
            "in_list_view": 1,
            "in_standard_filter": 1,
        },
    )
    doc.append(
        "fields",
        {
            "fieldname": "allow_transact",
            "label": "Allow Transact",
            "fieldtype": "Check",
            "default": "0",
            "in_list_view": 1,
            "in_standard_filter": 1,
        },
    )
    doc.append(
        "fields",
        {
            "fieldname": "is_default",
            "label": "Is Default",
            "fieldtype": "Check",
            "default": "0",
            "in_list_view": 1,
            "in_standard_filter": 1,
        },
    )

    doc.save(ignore_permissions=True)

    if frappe.db.has_column("Allowed Warehouse", "role_profile"):
        frappe.db.sql_ddl("ALTER TABLE `tabAllowed Warehouse` DROP COLUMN `role_profile`")

    frappe.clear_cache(doctype="Allowed Warehouse")
