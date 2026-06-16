import json

import frappe


TARGET_DOCTYPES = {
    "Customer Item History",
    "Customer Item Rate History",
}


def execute():
    fixture_doctypes = _load_doctype_fixtures()

    for name in sorted(TARGET_DOCTYPES):
        fixture = fixture_doctypes.get(name)
        if not fixture:
            frappe.throw(f"DocType fixture not found: {name}")

        _restore_doctype(name, fixture)


def _load_doctype_fixtures():
    fixture_path = frappe.get_app_path("qcmc_logic", "fixtures", "doctype.json")
    with open(fixture_path) as fixture:
        return {
            doctype.get("name"): doctype
            for doctype in json.load(fixture)
            if doctype.get("name")
        }


def _restore_doctype(name, fixture):
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
        "allow_rename",
        "autoname",
        "naming_rule",
        "rows_threshold_for_grid_search",
    ):
        doc.set(fieldname, fixture.get(fieldname))

    doc.set("fields", [])
    for field in fixture.get("fields") or []:
        doc.append("fields", _clean_child_row(field))

    doc.set("permissions", [])
    for permission in fixture.get("permissions") or []:
        doc.append("permissions", _clean_child_row(permission))

    doc.save(ignore_permissions=True)
    frappe.clear_cache(doctype=name)


def _clean_child_row(row):
    return {
        key: value
        for key, value in row.items()
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
