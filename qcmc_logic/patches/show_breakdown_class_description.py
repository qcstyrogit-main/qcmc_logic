import frappe


def execute():
    doctype = "Breakdown Class"
    if not frappe.db.exists("DocType", doctype):
        return

    frappe.db.set_value("DocType", doctype, {
        "title_field": "description",
        "show_title_field_in_link": 1,
        "search_fields": "description",
    })
    frappe.db.set_value("DocField", {
        "parent": doctype, "fieldname": "description",
    }, "in_list_view", 1)

    if frappe.db.exists("List View Settings", doctype):
        settings = frappe.get_doc("List View Settings", doctype)
    else:
        settings = frappe.new_doc("List View Settings")
        settings.name = doctype
    settings.fields = frappe.as_json([
        {"label": "Description", "fieldname": "description"},
    ])
    settings.save(ignore_permissions=True)
    # Refresh link-title metadata for every form referencing this master.
    frappe.clear_cache()
