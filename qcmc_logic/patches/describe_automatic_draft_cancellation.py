"""Update the setting help text without changing its saved value."""
import frappe


def execute():
    name = frappe.db.get_value("Custom Field", {
        "dt": "System Settings", "fieldname": "custom_allow_cancellation_before_submission"
    }, "name")
    if name:
        frappe.db.set_value("Custom Field", name, "description",
            "Automatically offer Cancel for authorized users on saved draft transactions, including active workflow states. No manual cancellation transitions are required. Existing explicit cancellation restrictions and dependency checks still apply.")
        frappe.clear_cache(doctype="System Settings")
