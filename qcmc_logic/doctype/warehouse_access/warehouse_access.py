import frappe
from frappe.model.document import Document

from qcmc_logic.utils import (
    _get_default_warehouse_from_source,
    get_user_allowed_warehouses,
)


def validate_default_warehouse(doc, method=None):
    defaults = [
        row.warehouse
        for row in doc.allowed_warehouses
        if getattr(row, "is_default", 0)
    ]
    if not doc.user:
        return

    other_access_names = frappe.get_all(
        "Warehouse Access",
        filters={
            "user": doc.user,
            "name": ["!=", doc.name],
        },
        pluck="name",
    )
    other_default_count = 0

    if other_access_names:
        other_default_count = frappe.db.count(
            "Allowed Warehouse",
            {
                "parent": ["in", other_access_names],
                "is_default": 1,
            },
        )

    default_count = len(defaults) + other_default_count

    if default_count == 0 and not _get_default_warehouse_from_source(
        doc.user,
        source="Role Profile",
    ):
        frappe.throw("Set one Allowed Warehouse as the default warehouse.")

    if default_count > 1:
        frappe.throw("Only one default Allowed Warehouse is allowed per user.")


def validate_role_profile_default_warehouse(doc, method=None):
    defaults = [
        row.warehouse
        for row in doc.allowed_warehouses
        if getattr(row, "is_default", 0)
    ]
    if not doc.role_profile:
        return

    other_access_names = frappe.get_all(
        "Role Profile Warehouse Access",
        filters={
            "role_profile": doc.role_profile,
            "name": ["!=", doc.name],
        },
        pluck="name",
    )
    other_default_count = 0

    if other_access_names:
        other_default_count = frappe.db.count(
            "Allowed Warehouse",
            {
                "parent": ["in", other_access_names],
                "is_default": 1,
            },
        )

    default_count = len(defaults) + other_default_count

    if default_count == 0:
        frappe.throw("Set one Allowed Warehouse as the default warehouse.")

    if default_count > 1:
        frappe.throw("Only one default Allowed Warehouse is allowed per role profile.")


def sync_effective_warehouse_user_permissions(user):
    if not user:
        return

    frappe.db.delete(
        "User Permission",
        {
            "user": user,
            "allow": "Warehouse",
        },
    )

    for warehouse in get_user_allowed_warehouses(user):
        up = frappe.new_doc("User Permission")
        up.user = user
        up.allow = "Warehouse"
        up.for_value = warehouse
        up.insert(ignore_permissions=True)


def get_users_for_role_profile(role_profile):
    if not role_profile:
        return []

    users = frappe.get_all(
        "User",
        filters={"role_profile_name": role_profile},
        pluck="name",
    )

    if frappe.db.table_exists("User Role Profile"):
        users.extend(
            frappe.get_all(
                "User Role Profile",
                filters={"role_profile": role_profile},
                pluck="parent",
            )
        )

    return list(dict.fromkeys(filter(None, users)))


def sync_role_profile_warehouse_user_permissions(doc, method=None):
    for user in get_users_for_role_profile(doc.role_profile):
        sync_effective_warehouse_user_permissions(user)


class WarehouseAccess(Document):
    def validate(self):
        self.validate_default_warehouse()

    def on_update(self):
        self.sync_user_permissions()

    def after_insert(self):
        self.sync_user_permissions()

    def after_delete(self):
        self.sync_user_permissions()

    def validate_default_warehouse(self):
        validate_default_warehouse(self)

    def sync_user_permissions(self):
        sync_effective_warehouse_user_permissions(self.user)
