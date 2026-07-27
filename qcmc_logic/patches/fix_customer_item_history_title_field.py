import frappe


def execute():
    doctype = "Customer Item History"

    if not frappe.db.exists("DocType", doctype):
        return

    meta = frappe.get_meta(doctype)
    if not meta.has_field("item"):
        return

    frappe.db.set_value("DocType", doctype, "title_field", "item")
    frappe.db.set_value("DocType", doctype, "show_title_field_in_link", 1)
    frappe.clear_cache(doctype=doctype)
