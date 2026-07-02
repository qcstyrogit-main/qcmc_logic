import frappe


FIELDNAMES = (
    "inventory_group",
    "allow_transact",
    "is_default",
)


def execute():
    if not frappe.db.exists("DocType", "Allowed Inventory Group"):
        return

    doctype = frappe.get_doc("DocType", "Allowed Inventory Group")
    fields_by_name = {field.fieldname: field for field in doctype.fields}

    changed = False
    for fieldname in FIELDNAMES:
        field = fields_by_name.get(fieldname)
        if field and field.hidden:
            field.hidden = 0
            changed = True

    if changed:
        doctype.save(ignore_permissions=True)

    frappe.clear_cache(doctype="Allowed Inventory Group")
