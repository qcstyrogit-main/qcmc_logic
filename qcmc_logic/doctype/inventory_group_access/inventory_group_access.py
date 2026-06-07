import frappe
from frappe.model.document import Document

from qcmc_logic.utils import _get_default_inventory_group_from_source


def validate_default_inventory_group(doc, method=None):
    defaults = [
        row.inventory_group
        for row in doc.allowed_inventory_groups
        if getattr(row, "is_default", 0)
    ]
    if not doc.user:
        return

    other_access_names = frappe.get_all(
        "Inventory Group Access",
        filters={
            "user": doc.user,
            "name": ["!=", doc.name],
        },
        pluck="name",
    )
    other_default_count = 0

    if other_access_names:
        other_default_count = frappe.db.count(
            "Allowed Inventory Group",
            {
                "parent": ["in", other_access_names],
                "is_default": 1,
            },
        )

    default_count = len(defaults) + other_default_count

    if default_count == 0 and not _get_default_inventory_group_from_source(
        doc.user,
        source="Role Profile",
    ):
        frappe.throw("Set one Allowed Inventory Group as the default inventory group.")

    if default_count > 1:
        frappe.throw("Only one default Allowed Inventory Group is allowed per user.")


def validate_role_profile_default_inventory_group(doc, method=None):
    defaults = [
        row.inventory_group
        for row in doc.allowed_inventory_groups
        if getattr(row, "is_default", 0)
    ]
    if not doc.role_profile:
        return

    other_access_names = frappe.get_all(
        "Role Profile Inventory Group Access",
        filters={
            "role_profile": doc.role_profile,
            "name": ["!=", doc.name],
        },
        pluck="name",
    )
    other_default_count = 0

    if other_access_names:
        other_default_count = frappe.db.count(
            "Allowed Inventory Group",
            {
                "parent": ["in", other_access_names],
                "is_default": 1,
            },
        )

    default_count = len(defaults) + other_default_count

    if default_count == 0:
        frappe.throw("Set one Allowed Inventory Group as the default inventory group.")

    if default_count > 1:
        frappe.throw(
            "Only one default Allowed Inventory Group is allowed per role profile."
        )


class InventoryGroupAccess(Document):
    def validate(self):
        validate_default_inventory_group(self)
