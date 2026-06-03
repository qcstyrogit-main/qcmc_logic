import frappe


def execute():
    if frappe.db.exists("DocType", "Allowed Warehouse"):
        doc = frappe.get_doc("DocType", "Allowed Warehouse")
        if not any(field.fieldname == "is_default" for field in doc.fields):
            doc.append(
                "fields",
                {
                    "fieldname": "is_default",
                    "label": "Is Default",
                    "fieldtype": "Check",
                    "default": "0",
                    "in_list_view": 1,
                    "in_standard_filter": 1,
                    "in_filter": 1,
                },
            )
            doc.save(ignore_permissions=True)

    frappe.clear_cache(doctype="Allowed Warehouse")
