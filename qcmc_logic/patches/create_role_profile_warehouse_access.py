import frappe


def execute():
    if frappe.db.exists("DocType", "Role Profile Warehouse Access"):
        return

    doc = frappe.get_doc(
        {
            "doctype": "DocType",
            "name": "Role Profile Warehouse Access",
            "module": "QCMC Logics",
            "custom": 1,
            "allow_rename": 1,
            "editable_grid": 0,
            "title_field": "role_profile",
            "fields": [
                {
                    "fieldname": "role_profile",
                    "fieldtype": "Link",
                    "label": "Role Profile",
                    "options": "Role Profile",
                    "in_list_view": 1,
                    "reqd": 1,
                    "unique": 1,
                },
                {
                    "fieldname": "allowed_warehouses",
                    "fieldtype": "Table",
                    "label": "Allowed Warehouses",
                    "options": "Allowed Warehouse",
                },
            ],
            "permissions": [
                {
                    "role": "System Manager",
                    "read": 1,
                    "write": 1,
                    "create": 1,
                    "delete": 1,
                    "print": 1,
                    "email": 1,
                    "report": 1,
                    "export": 1,
                    "share": 1,
                }
            ],
        }
    )
    doc.insert(ignore_permissions=True)
