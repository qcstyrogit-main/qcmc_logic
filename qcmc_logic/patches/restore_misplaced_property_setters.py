import json

import frappe


def execute():
    fixture_setters = _load_property_setter_fixtures()

    for name, fixture in fixture_setters.items():
        parsed = _parse_property_setter_name(fixture)
        if not parsed:
            continue

        expected_doc_type, expected_field_name, expected_property = parsed
        if (
            fixture.get("doc_type"),
            fixture.get("field_name"),
            fixture.get("property"),
        ) != (expected_doc_type, expected_field_name, expected_property):
            continue

        if not frappe.db.exists("Property Setter", name):
            continue

        current = frappe.db.get_value(
            "Property Setter",
            name,
            ["doc_type", "field_name", "property"],
            as_dict=True,
        )
        if (
            current.doc_type,
            current.field_name,
            current.property,
        ) == (expected_doc_type, expected_field_name, expected_property):
            continue

        frappe.db.set_value(
            "Property Setter",
            name,
            {
                "doc_type": expected_doc_type,
                "field_name": expected_field_name,
                "property": expected_property,
            },
            update_modified=False,
        )

    frappe.clear_cache()


def _load_property_setter_fixtures():
    fixture_path = frappe.get_app_path("qcmc_logic", "fixtures", "property_setter.json")
    with open(fixture_path) as fixture:
        return {
            setter.get("name"): setter
            for setter in json.load(fixture)
            if setter.get("name")
        }


def _parse_property_setter_name(setter):
    name = setter.get("name") or ""
    property_name = setter.get("property")
    doctype_or_field = setter.get("doctype_or_field")

    if not property_name or not name.endswith(f"-{property_name}"):
        return None

    target = name[: -(len(property_name) + 1)]
    if doctype_or_field == "DocType":
        if not target.endswith("-main"):
            return None
        return target[:-5], None, property_name

    if doctype_or_field != "DocField" or "-" not in target:
        return None

    doc_type, field_name = target.rsplit("-", 1)
    return doc_type, field_name, property_name
