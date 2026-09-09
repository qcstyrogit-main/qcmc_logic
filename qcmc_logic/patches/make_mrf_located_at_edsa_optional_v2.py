"""Keep the MRF EDSA checkbox optional, including after fixture synchronization."""

import frappe
from frappe.custom.doctype.property_setter.property_setter import make_property_setter


def execute():
    doctype = "Job Requisition"
    fieldname = "custom_located_at_edsa"
    if not frappe.db.exists("DocType", doctype):
        return

    custom_field = frappe.db.get_value(
        "Custom Field", {"dt": doctype, "fieldname": fieldname}, "name"
    )
    if custom_field:
        frappe.db.set_value(
            "Custom Field",
            custom_field,
            {"reqd": 0, "mandatory_depends_on": ""},
            update_modified=False,
        )

    # Overrides also protect against an older Custom Field fixture being imported.
    # The helper replaces existing setters for each property on this field.
    for property_name, value, property_type in (
        ("reqd", "0", "Check"),
        ("mandatory_depends_on", "", "Data"),
    ):
        make_property_setter(
            doctype,
            fieldname,
            property_name,
            value,
            property_type,
            validate_fields_for_doctype=False,
        )

    frappe.clear_cache(doctype=doctype)
