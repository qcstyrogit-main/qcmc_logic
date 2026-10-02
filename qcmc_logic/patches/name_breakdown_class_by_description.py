import frappe
from frappe.model.rename_doc import rename_doc


def execute():
    doctype = "Breakdown Class"
    if not frappe.db.exists("DocType", doctype):
        return

    rows = frappe.get_all(doctype, fields=["name", "description"])
    names = {row.name for row in rows}
    descriptions = set()
    for row in rows:
        description = (row.description or "").strip()
        if not description or len(description) > 140:
            frappe.throw(f"Breakdown Class {row.name} needs a Description of 1–140 characters.")
        if description.casefold() in descriptions:
            frappe.throw(f"Duplicate Breakdown Class Description: {description}")
        if description != row.name and description in names:
            frappe.throw(f"Breakdown Class name already exists: {description}")
        descriptions.add(description.casefold())

    meta = frappe.get_doc("DocType", doctype)
    meta.autoname = "field:description"
    meta.naming_rule = "By fieldname"
    meta.title_field = "description"
    meta.show_title_field_in_link = 1
    meta.search_fields = "description"
    next(field for field in meta.fields if field.fieldname == "description").reqd = 1
    meta.save(ignore_permissions=True)
    frappe.clear_cache(doctype=doctype)

    for row in rows:
        description = row.description.strip()
        if row.description != description:
            frappe.db.set_value(doctype, row.name, "description", description)
        if row.name != description:
            # Frappe updates Link and Dynamic Link references during the rename.
            rename_doc(doctype, row.name, description, ignore_permissions=True)

    frappe.clear_cache()
