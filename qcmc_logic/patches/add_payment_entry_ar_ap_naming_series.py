import frappe
from frappe.custom.doctype.property_setter.property_setter import make_property_setter


PAYMENT_ENTRY_SERIES_OPTIONS = "ACC-REC-.YYYY.-\nACC-PAY-.YYYY.-"


def execute():
    make_property_setter(
        "Payment Entry",
        "naming_series",
        "options",
        PAYMENT_ENTRY_SERIES_OPTIONS,
        "Text",
    )
    frappe.clear_cache(doctype="Payment Entry")
