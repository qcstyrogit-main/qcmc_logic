"""Descriptive document titles without changing primary keys."""
import frappe

TITLED = ("Reorder Policy Mapping", "Item Reorder Override", "Reorder Calculation History")

def make_title(doc):
    scope = doc.get("item_code") or doc.get("item_group") or "All Items"
    warehouse = doc.get("warehouse") or "All Warehouses"
    parts = [scope, warehouse]
    if doc.doctype == "Reorder Calculation History":
        parts.append(doc.get("calculation_date"))
    return " | ".join(str(p) for p in parts if p)[:140]

def set_title(doc, method=None):
    doc.display_title = make_title(doc)

def install_titles():
    for name in TITLED:
        meta = frappe.get_doc("DocType", name)
        if not any(f.fieldname == "display_title" for f in meta.fields):
            meta.append("fields", dict(fieldname="display_title", label="Display Name",
                fieldtype="Data", read_only=1, hidden=1, no_copy=1))
        meta.title_field = "display_title"
        meta.show_title_field_in_link = 1
        meta.search_fields = "display_title,item_code,warehouse"
        meta.save()
        frappe.clear_cache(doctype=name)
        fields = ["name", "item_code", "warehouse", "display_title"]
        if name == "Reorder Policy Mapping":
            fields.append("item_group")
        if name == "Reorder Calculation History":
            fields.append("calculation_date")
        for row in frappe.get_all(name, fields=fields):
            row.doctype = name
            title = make_title(row)
            if row.display_title != title:
                frappe.db.set_value(name, row.name, "display_title", title, update_modified=False)
