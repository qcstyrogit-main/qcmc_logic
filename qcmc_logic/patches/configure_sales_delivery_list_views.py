import json

import frappe
from frappe.custom.doctype.property_setter.property_setter import make_property_setter


LIST_VIEW_COLUMNS = {
    "Delivery Note": [
        {"fieldname": "name", "label": "ID"},
        {"fieldname": "customer_name", "label": "Customer Name"},
        {"fieldname": "custom_sales_order", "label": "Sales Order"},
        {"fieldname": "status_field", "label": "Status"},
        {"fieldname": "posting_date", "label": "Date"},
        {"fieldname": "custom_dr_number", "label": "DR Number"},
    ],
    "Sales Invoice": [
        {"fieldname": "name", "label": "ID"},
        {"fieldname": "customer_name", "label": "Customer Name"},
        {"fieldname": "territory", "label": "Territory"},
        {"fieldname": "company", "label": "Company"},
        {"fieldname": "custom_invoice_number", "label": "Invoice Number"},
    ],
}

LIST_VIEW_FLAGS = {
    "Delivery Note": {
        "enable": ("customer_name", "custom_dr_number"),
        "disable": ("customer", "per_billed", "per_returned", "set_target_warehouse", "title"),
    },
    "Sales Invoice": {
        "enable": ("customer_name", "custom_invoice_number"),
        "disable": ("customer", "outstanding_amount", "status_field", "grand_total", "rounded_total"),
    },
}


def execute():
    for doctype, fields in LIST_VIEW_COLUMNS.items():
        if not frappe.db.exists("DocType", doctype):
            continue

        if doctype == "Delivery Note":
            set_property(doctype, None, "title_field", "", "Data", doctype_or_field="DocType")

        configure_list_view_settings(doctype, fields)
        configure_list_view_flags(doctype)
        frappe.clear_cache(doctype=doctype)

    frappe.clear_cache(doctype="List View Settings")


def configure_list_view_settings(doctype, fields):
    value = json.dumps(fields, separators=(",", ":"))
    if frappe.db.exists("List View Settings", doctype):
        doc = frappe.get_doc("List View Settings", doctype)
        doc.fields = value
        doc.save(ignore_permissions=True)
    else:
        frappe.get_doc(
            {
                "doctype": "List View Settings",
                "name": doctype,
                "fields": value,
            }
        ).insert(ignore_permissions=True)


def configure_list_view_flags(doctype):
    flags = LIST_VIEW_FLAGS[doctype]
    for fieldname in flags["enable"]:
        set_in_list_view(doctype, fieldname, 1)
    for fieldname in flags["disable"]:
        set_in_list_view(doctype, fieldname, 0)


def set_in_list_view(doctype, fieldname, value):
    custom_field = frappe.db.exists("Custom Field", {"dt": doctype, "fieldname": fieldname})
    if custom_field:
        frappe.db.set_value(
            "Custom Field",
            custom_field,
            "in_list_view",
            value,
            update_modified=False,
        )
        return

    if frappe.db.exists("DocField", {"parent": doctype, "fieldname": fieldname}):
        set_property(doctype, fieldname, "in_list_view", str(value), "Check")


def set_property(doctype, fieldname, property_name, value, property_type, doctype_or_field="DocField"):
    setter_name = get_property_setter_name(doctype, fieldname, property_name)
    if frappe.db.exists("Property Setter", setter_name):
        frappe.db.set_value(
            "Property Setter",
            setter_name,
            "value",
            value,
            update_modified=False,
        )
        return

    make_property_setter(
        doctype,
        fieldname,
        property_name,
        value,
        property_type,
        for_doctype=doctype_or_field == "DocType",
    )


def get_property_setter_name(doctype, fieldname, property_name):
    if fieldname:
        return f"{doctype}-{fieldname}-{property_name}"
    return f"{doctype}-main-{property_name}"
