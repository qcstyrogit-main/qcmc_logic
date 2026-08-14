import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


PAYMENT_ENTRY_ROLES = ("AR User", "AP User")


def execute():
    create_payment_entry_roles()
    add_accounts_settings_toggle()
    frappe.clear_cache(doctype="Role")
    frappe.clear_cache(doctype="Accounts Settings")
    frappe.clear_cache(doctype="Payment Entry")


def create_payment_entry_roles():
    for role_name in PAYMENT_ENTRY_ROLES:
        if frappe.db.exists("Role", role_name):
            continue

        role = frappe.new_doc("Role")
        role.role_name = role_name
        role.desk_access = 1
        role.insert(ignore_permissions=True)


def add_accounts_settings_toggle():
    create_custom_fields(
        {
            "Accounts Settings": [
                {
                    "fieldname": "custom_enforce_payment_entry_type_by_role",
                    "fieldtype": "Check",
                    "label": "Enforce Payment Entry Type by AR/AP Role",
                    "insert_after": "unlink_payment_on_cancellation_of_invoice",
                    "default": "0",
                    "description": (
                        "When enabled, AR User can create only Receive Payment Entries "
                        "and AP User can create only Pay Payment Entries."
                    ),
                },
            ],
        },
        ignore_validate=True,
    )
