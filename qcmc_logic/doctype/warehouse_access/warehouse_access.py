import frappe
from frappe.model.document import Document


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

    if default_count == 0:
        frappe.throw("Set one Allowed Warehouse as the default warehouse.")

    if default_count > 1:
        frappe.throw("Only one default Allowed Warehouse is allowed per user.")


class WarehouseAccess(Document):
    def validate(self):
        self.validate_default_warehouse()

    def on_update(self):
        self.sync_user_permissions()

    def after_insert(self):
        self.sync_user_permissions()

    def validate_default_warehouse(self):
        validate_default_warehouse(self)

    def sync_user_permissions(self):
        frappe.db.delete(
            "User Permission",
            {
                "user": self.user,
                "allow": "Warehouse",
            },
        )

        for row in self.allowed_warehouses:
            if not row.warehouse:
                continue

            if frappe.db.exists(
                "User Permission",
                {
                    "user": self.user,
                    "allow": "Warehouse",
                    "for_value": row.warehouse,
                },
            ):
                continue

            up = frappe.new_doc("User Permission")
            up.user = self.user
            up.allow = "Warehouse"
            up.for_value = row.warehouse
            up.insert(ignore_permissions=True)
