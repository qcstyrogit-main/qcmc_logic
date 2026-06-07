import frappe


def execute():
    create_allowed_inventory_group()
    create_inventory_group_access()
    create_role_profile_inventory_group_access()


def create_allowed_inventory_group():
    if frappe.db.exists("DocType", "Allowed Inventory Group"):
        return

    doc = frappe.get_doc(
        {
            "doctype": "DocType",
            "name": "Allowed Inventory Group",
            "module": "Stock",
            "custom": 1,
            "allow_rename": 1,
            "editable_grid": 1,
            "istable": 1,
            "fields": [
                {
                    "fieldname": "inventory_group",
                    "fieldtype": "Link",
                    "label": "Inventory Group",
                    "options": "Inventory Group",
                    "in_list_view": 1,
                    "in_standard_filter": 1,
                },
                {
                    "fieldname": "allow_transact",
                    "fieldtype": "Check",
                    "label": "Allow Transact",
                    "default": "0",
                    "in_list_view": 1,
                    "in_standard_filter": 1,
                },
                {
                    "fieldname": "is_default",
                    "fieldtype": "Check",
                    "label": "Is Default",
                    "default": "0",
                    "in_list_view": 1,
                    "in_standard_filter": 1,
                },
            ],
        }
    )
    doc.insert(ignore_permissions=True)


def create_inventory_group_access():
    if frappe.db.exists("DocType", "Inventory Group Access"):
        return

    doc = frappe.get_doc(
        {
            "doctype": "DocType",
            "name": "Inventory Group Access",
            "module": "QCMC Logics",
            "custom": 1,
            "allow_rename": 1,
            "editable_grid": 0,
            "title_field": "user",
            "fields": [
                {
                    "fieldname": "user",
                    "fieldtype": "Link",
                    "label": "User",
                    "options": "User",
                    "in_list_view": 1,
                    "reqd": 1,
                    "unique": 1,
                },
                {
                    "fieldname": "allowed_inventory_groups",
                    "fieldtype": "Table",
                    "label": "Allowed Inventory Groups",
                    "options": "Allowed Inventory Group",
                },
            ],
            "permissions": [_system_manager_permission()],
        }
    )
    doc.insert(ignore_permissions=True)


def create_role_profile_inventory_group_access():
    if frappe.db.exists("DocType", "Role Profile Inventory Group Access"):
        return

    doc = frappe.get_doc(
        {
            "doctype": "DocType",
            "name": "Role Profile Inventory Group Access",
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
                    "fieldname": "allowed_inventory_groups",
                    "fieldtype": "Table",
                    "label": "Allowed Inventory Groups",
                    "options": "Allowed Inventory Group",
                },
            ],
            "permissions": [_system_manager_permission()],
        }
    )
    doc.insert(ignore_permissions=True)


def _system_manager_permission():
    return {
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
