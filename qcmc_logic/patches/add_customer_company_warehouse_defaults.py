import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


CHILD_DOCTYPE = "Customer Company Warehouse Default"
PARENT_FIELD = "custom_company_warehouse_defaults"


def execute():
    ensure_child_doctype()
    create_custom_fields(
        {
            "Customer": [
                {
                    "fieldname": PARENT_FIELD,
                    "label": "Company Warehouse Defaults",
                    "fieldtype": "Table",
                    "options": CHILD_DOCTYPE,
                    "insert_after": "accounts",
                },
            ]
        },
        ignore_validate=True,
    )

    frappe.db.add_index(
        CHILD_DOCTYPE,
        ["parent", "parenttype", "parentfield", "company"],
        "customer_company_wh_default_idx",
    )
    frappe.clear_cache(doctype="Customer")
    frappe.clear_cache(doctype=CHILD_DOCTYPE)


def ensure_child_doctype():
    if frappe.db.exists("DocType", CHILD_DOCTYPE):
        doc = frappe.get_doc("DocType", CHILD_DOCTYPE)
    else:
        doc = frappe.new_doc("DocType")
        doc.name = CHILD_DOCTYPE

    doc.module = "Selling"
    doc.custom = 1
    doc.istable = 1
    doc.editable_grid = 1
    doc.title_field = "company"
    doc.sort_field = "idx"
    doc.sort_order = "ASC"
    doc.permissions = []
    doc.fields = []

    doc.append(
        "fields",
        {
            "fieldname": "company",
            "label": "Company",
            "fieldtype": "Link",
            "options": "Company",
            "reqd": 1,
            "in_list_view": 1,
            "in_standard_filter": 1,
        },
    )
    doc.append(
        "fields",
        {
            "fieldname": "warehouse",
            "label": "Warehouse",
            "fieldtype": "Link",
            "options": "Warehouse",
            "reqd": 1,
            "in_list_view": 1,
            "in_standard_filter": 1,
        },
    )

    if doc.is_new():
        doc.insert(ignore_permissions=True)
    else:
        doc.save(ignore_permissions=True)
