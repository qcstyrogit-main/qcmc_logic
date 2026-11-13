import frappe


DOCTYPE = "Maintenance Job Order"
FIELDNAME = "request_flow"


def execute():
    if not frappe.db.exists("DocType", DOCTYPE):
        return

    for name in frappe.get_all(
        "Custom Field", filters={"dt": DOCTYPE, "fieldname": FIELDNAME}, pluck="name"
    ):
        frappe.delete_doc("Custom Field", name, ignore_permissions=True)

    doctype = frappe.get_doc("DocType", DOCTYPE)
    if any(field.fieldname == FIELDNAME for field in doctype.fields):
        doctype.set("fields", [field for field in doctype.fields if field.fieldname != FIELDNAME])
        doctype.save(ignore_permissions=True)

    for name in frappe.get_all(
        "Property Setter", filters={"doc_type": DOCTYPE, "field_name": FIELDNAME}, pluck="name"
    ):
        frappe.delete_doc("Property Setter", name, ignore_permissions=True)

    frappe.clear_cache(doctype=DOCTYPE)
