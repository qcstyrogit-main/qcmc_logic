import frappe


def execute():
    if not frappe.db.exists("DocType", "Allowed Warehouse"):
        return

    doc = frappe.get_doc("DocType", "Allowed Warehouse")
    if not any(field.fieldname == "allow_in_list_view" for field in doc.fields):
        doc.append(
            "fields",
            {
                "fieldname": "allow_in_list_view",
                "label": "Allow in List View",
                "fieldtype": "Check",
                "default": "0",
                "in_list_view": 1,
                "in_standard_filter": 1,
                "in_filter": 1,
            },
        )
        doc.save(ignore_permissions=True)

    if frappe.db.has_column("Allowed Warehouse", "allow_in_list_view"):
        if not frappe.db.exists("Allowed Warehouse", {"allow_in_list_view": 1}):
            frappe.db.sql(
                """
                update `tabAllowed Warehouse`
                set allow_in_list_view = ifnull(allow_transact, 0)
                where ifnull(allow_in_list_view, 0) = 0
                """
            )
        frappe.db.add_index(
            "Allowed Warehouse",
            ["parent", "allow_in_list_view", "warehouse"],
            "allowed_warehouse_list_view_idx",
        )

    frappe.clear_cache(doctype="Allowed Warehouse")
