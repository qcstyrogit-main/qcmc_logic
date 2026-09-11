import frappe


def execute():
    if not frappe.db.exists("DocType", "Warehouse Transfer Details"):
        return

    doc = frappe.get_doc("DocType", "Warehouse Transfer Details")
    changed = False

    for field in doc.fields:
        if field.fieldname == "material_request":
            field.hidden = 0
            field.in_list_view = 1
            field.read_only = 1
            field.no_copy = 1
            field.print_hide = 1
            changed = True
            break

    if changed:
        doc.save(ignore_permissions=True)

    frappe.clear_cache(doctype="Warehouse Transfer Details")
