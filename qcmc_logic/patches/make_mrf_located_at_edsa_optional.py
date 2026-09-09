import frappe


def execute():
    doctype = "Job Requisition"
    fieldname = "custom_located_at_edsa"
    custom_field = frappe.db.get_value(
        "Custom Field", {"dt": doctype, "fieldname": fieldname}, "name"
    )
    if not custom_field:
        return

    frappe.db.set_value(
        "Custom Field", custom_field, "reqd", 0, update_modified=False
    )

    # Existing site customizations can override the Custom Field definition.
    for setter in frappe.get_all(
        "Property Setter",
        filters={"doc_type": doctype, "field_name": fieldname, "property": "reqd"},
        pluck="name",
    ):
        frappe.db.set_value(
            "Property Setter", setter, "value", "0", update_modified=False
        )

    frappe.clear_cache(doctype=doctype)
