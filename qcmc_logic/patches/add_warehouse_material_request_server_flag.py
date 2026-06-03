import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
    create_custom_fields(
        {
            "Warehouse": [
                {
                    "fieldname": "custom_can_serve_material_requests",
                    "label": "Can Serve Material Requests",
                    "fieldtype": "Check",
                    "insert_after": "custom_is_province",
                    "description": (
                        "Allow this warehouse to be selected as the requested-from "
                        "warehouse on Material Transfer requests."
                    ),
                }
            ]
        },
        ignore_validate=True,
    )

    frappe.clear_cache(doctype="Warehouse")
