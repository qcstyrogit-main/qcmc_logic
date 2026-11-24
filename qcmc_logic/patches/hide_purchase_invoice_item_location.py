"""Hide the Purchase Invoice Item Location dimension on AP voucher entry only.

Keeps the underlying field and existing row values intact; this does not
delete an Inventory Dimension or change any other stock transaction DocType.
"""
import frappe
from frappe.custom.doctype.property_setter.property_setter import make_property_setter


def execute():
    dt = "Purchase Invoice Item"
    meta = frappe.get_meta(dt)
    # The branch Location and stock Target Location are separate fields.
    for fieldname in ("location", "custom_location"):
        if not meta.has_field(fieldname):
            continue

        # Hidden fields must not block saving new vouchers.
        for prop, value, kind in (
            ("reqd", 0, "Check"),
            ("hidden", 1, "Check"),
            ("in_list_view", 0, "Check"),
        ):
            make_property_setter(dt, fieldname, prop, value, kind, for_doctype=False)

    frappe.clear_cache(doctype=dt)
