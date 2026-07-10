import frappe


def execute():
    indexes = {
        "Warehouse Access": [
            (["user"], "warehouse_access_user_idx"),
        ],
        "Role Profile Warehouse Access": [
            (["role_profile"], "role_profile_warehouse_access_profile_idx"),
        ],
        "Inventory Group Access": [
            (["user"], "inventory_group_access_user_idx"),
        ],
        "Role Profile Inventory Group Access": [
            (["role_profile"], "role_profile_inventory_group_access_profile_idx"),
        ],
        "Allowed Warehouse": [
            (["parent", "warehouse"], "allowed_warehouse_parent_warehouse_idx"),
            (["parent", "allow_transact", "warehouse"], "allowed_warehouse_transact_idx"),
            (["parent", "is_default", "warehouse"], "allowed_warehouse_default_idx"),
        ],
        "Allowed Inventory Group": [
            (
                ["parent", "inventory_group"],
                "allowed_inventory_group_parent_group_idx",
            ),
            (
                ["parent", "allow_transact", "inventory_group"],
                "allowed_inventory_group_transact_idx",
            ),
            (
                ["parent", "is_default", "inventory_group"],
                "allowed_inventory_group_default_idx",
            ),
        ],
    }

    if frappe.db.table_exists("User Role Profile"):
        indexes["User Role Profile"] = [
            (["parent", "role_profile"], "user_role_profile_parent_profile_idx"),
        ]

    for doctype, doctype_indexes in indexes.items():
        if not frappe.db.table_exists(doctype):
            continue

        for fields, index_name in doctype_indexes:
            frappe.db.add_index(doctype, fields, index_name)
