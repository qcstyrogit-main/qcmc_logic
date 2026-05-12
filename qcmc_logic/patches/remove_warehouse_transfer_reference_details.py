import frappe


def execute():
    parent_doctype = "Warehouse Transfer"

    for fieldname in ("reference_details", "reference_details_section"):
        for field in frappe.get_all(
            "DocField",
            filters={"parent": parent_doctype, "fieldname": fieldname},
            pluck="name",
        ):
            frappe.delete_doc("DocField", field, ignore_permissions=True, force=True)

    for client_script in ("WT_referencedoc_fetchItems", "WT_WHFILTERS"):
        if frappe.db.exists("Client Script", client_script):
            frappe.db.set_value("Client Script", client_script, "enabled", 0)

    frappe.clear_cache(doctype=parent_doctype)
