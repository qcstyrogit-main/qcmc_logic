import frappe


def execute():
    doctype = "Customer Item History"
    fieldname = "last_uom"

    if not frappe.db.exists("DocType", doctype):
        return

    field = frappe.db.get_value(
        "DocField",
        {"parent": doctype, "fieldname": fieldname},
        "name",
    )
    if not field:
        return

    frappe.db.set_value(
        "DocField",
        field,
        {
            "reqd": 0,
            "fetch_from": "item.stock_uom",
            "fetch_if_empty": 1,
        },
    )
    frappe.clear_cache(doctype=doctype)
