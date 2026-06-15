import frappe


def execute():
    fields = [
        {
            "fieldname": "warehouse",
            "label": "Warehouse",
            "fieldtype": "Link",
            "options": "Warehouse",
            "in_list_view": 1,
            "in_standard_filter": 1,
            "in_filter": 1,
        },
        {
            "fieldname": "allow_transact",
            "label": "Allow Transact",
            "fieldtype": "Check",
            "default": "0",
            "in_list_view": 1,
            "in_standard_filter": 1,
            "in_filter": 1,
        },
        {
            "fieldname": "is_default",
            "label": "Is Default",
            "fieldtype": "Check",
            "default": "0",
            "in_list_view": 1,
            "in_standard_filter": 1,
            "in_filter": 1,
        },
    ]

    if frappe.db.exists("DocType", "Allowed Warehouse"):
        doc = frappe.get_doc("DocType", "Allowed Warehouse")
    else:
        doc = frappe.new_doc("DocType")
        doc.name = "Allowed Warehouse"

    doc.module = "Stock"
    doc.custom = 1
    doc.allow_rename = 1
    doc.editable_grid = 1
    doc.istable = 1
    doc.title_field = None
    doc.sort_field = "modified"
    doc.rows_threshold_for_grid_search = 0
    doc.set("permissions", [])
    doc.set("fields", [])

    for field in fields:
        doc.append("fields", field)

    if doc.is_new():
        doc.insert(ignore_permissions=True)
    else:
        doc.save(ignore_permissions=True)

    frappe.clear_cache(doctype="Allowed Warehouse")
