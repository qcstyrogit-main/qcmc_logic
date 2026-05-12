import frappe


def execute():
    child_doctype = "Stock Entry Reference Detail"
    parent_doctype = "Warehouse Transfer"

    for fieldname in ("reference_details", "reference_details_section"):
        for field in frappe.get_all(
            "DocField",
            filters={"parent": parent_doctype, "fieldname": fieldname},
            pluck="name",
        ):
            frappe.delete_doc("DocField", field, ignore_permissions=True, force=True)

    for field in frappe.get_all(
        "DocField",
        filters={"parent": child_doctype, "fieldname": "reference_type"},
        pluck="name",
    ):
        frappe.delete_doc("DocField", field, ignore_permissions=True, force=True)

    reference_name = frappe.db.get_value(
        "DocField",
        {"parent": child_doctype, "fieldname": "reference_name"},
        "name",
    )
    if reference_name:
        frappe.db.set_value(
            "DocField",
            reference_name,
            {
                "fieldtype": "Link",
                "options": "Material Request",
                "depends_on": None,
                "label": "Material Request",
                "reqd": 1,
            },
        )

    frappe.clear_cache(doctype=child_doctype)
    frappe.clear_cache(doctype=parent_doctype)

    for client_script in ("WT_referencedoc_fetchItems", "WT_WHFILTERS"):
        if frappe.db.exists("Client Script", client_script):
            frappe.db.set_value("Client Script", client_script, "enabled", 0)
