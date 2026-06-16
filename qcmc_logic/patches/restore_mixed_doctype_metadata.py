import json

import frappe


TARGET_DOCTYPES = {
    "Allowed Warehouse",
    "Batch Leave Approval Detail",
    "Vehicle Log Attendant",
}


def _get_fixture_doctype(name):
    fixture_path = frappe.get_app_path("qcmc_logic", "fixtures", "doctype.json")
    with open(fixture_path) as fixture:
        doctypes = json.load(fixture)

    for doctype in doctypes:
        if doctype.get("name") == name:
            return doctype

    frappe.throw(f"DocType fixture not found: {name}")


def _restore_doctype_metadata(name):
    fixture = _get_fixture_doctype(name)
    doc = frappe.get_doc("DocType", name)

    for fieldname in (
        "module",
        "custom",
        "istable",
        "issingle",
        "is_submittable",
        "editable_grid",
        "title_field",
        "sort_field",
        "sort_order",
    ):
        doc.set(fieldname, fixture.get(fieldname))

    doc.fields = []
    for field in fixture.get("fields") or []:
        clean_field = {
            key: value
            for key, value in field.items()
            if key
            not in {
                "name",
                "owner",
                "creation",
                "modified",
                "modified_by",
                "parent",
                "parentfield",
                "parenttype",
                "doctype",
            }
        }
        doc.append("fields", clean_field)

    doc.permissions = []
    for permission in fixture.get("permissions") or []:
        clean_permission = {
            key: value
            for key, value in permission.items()
            if key
            not in {
                "name",
                "owner",
                "creation",
                "modified",
                "modified_by",
                "parent",
                "parentfield",
                "parenttype",
                "doctype",
            }
        }
        doc.append("permissions", clean_permission)

    doc.save(ignore_permissions=True)
    frappe.clear_cache(doctype=name)


def execute():
    for doctype in TARGET_DOCTYPES:
        _restore_doctype_metadata(doctype)

    if frappe.db.has_column("Allowed Warehouse", "role_profile"):
        frappe.db.sql_ddl("ALTER TABLE `tabAllowed Warehouse` DROP COLUMN `role_profile`")
