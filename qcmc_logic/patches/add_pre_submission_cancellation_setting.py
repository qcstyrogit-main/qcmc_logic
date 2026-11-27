"""Install the site-wide opt-in. Preserve any existing administrator choice."""
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
    create_custom_fields({"System Settings": [
        {"fieldname": "custom_transaction_cancellation_section", "label": "Transaction Cancellation",
         "fieldtype": "Section Break", "insert_after": "log_api_requests"},
        {"fieldname": "custom_allow_cancellation_before_submission",
         "label": "Allow Cancellation Before Submission", "fieldtype": "Check", "default": "0",
         "insert_after": "custom_transaction_cancellation_section",
         "description": "Allow authorized cancellation of saved draft transactions, without submitting them. Existing workflow permissions and dependency checks still apply."},
    ]}, update=False)
