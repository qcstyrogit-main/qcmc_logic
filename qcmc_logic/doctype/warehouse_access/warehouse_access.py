import frappe
from frappe.model.document import Document

class WarehouseAccess(Document):
    def on_update(self):
        self.sync_user_permissions()

    def after_insert(self):
        self.sync_user_permissions()

    def sync_user_permissions(self):
        # Clear old Warehouse User Permissions for this user
        frappe.db.delete("User Permission", {
            "user": self.user,
            "allow": "Warehouse"
        })

        # Recreate from child table
        for row in self.allowed_warehouses:
            if row.warehouse:
                if not frappe.db.exists("User Permission", {
                    "user": self.user,
                    "allow": "Warehouse",
                    "for_value": row.warehouse
                }):
                    up = frappe.new_doc("User Permission")
                    up.user = self.user
                    up.allow = "Warehouse"
                    up.for_value = row.warehouse
                    up.insert(ignore_permissions=True)