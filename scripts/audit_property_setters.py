#!/usr/bin/env python3
"""Audit Property Setter fixtures for target metadata drift."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = ROOT / "qcmc_logic" / "fixtures" / "property_setter.json"


def main() -> int:
    setters = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    issues = []

    for row in setters:
        parsed = parse_property_setter_name(row)
        if not parsed:
            issues.append(
                "{name}: cannot parse target from name".format(
                    name=row.get("name") or "<missing name>"
                )
            )
            continue

        expected_doc_type, expected_field_name, expected_property = parsed
        actual = (
            row.get("doc_type"),
            row.get("field_name"),
            row.get("property"),
        )
        expected = (
            expected_doc_type,
            expected_field_name,
            expected_property,
        )

        if actual != expected:
            issues.append(
                "{name}: expected doc_type={expected_doc_type!r}, "
                "field_name={expected_field_name!r}, property={expected_property!r}; "
                "found doc_type={actual_doc_type!r}, field_name={actual_field_name!r}, "
                "property={actual_property!r}".format(
                    name=row.get("name"),
                    expected_doc_type=expected_doc_type,
                    expected_field_name=expected_field_name,
                    expected_property=expected_property,
                    actual_doc_type=row.get("doc_type"),
                    actual_field_name=row.get("field_name"),
                    actual_property=row.get("property"),
                )
            )

    if issues:
        print("Property Setter fixture audit failed:")
        for issue in issues:
            print(f"- {issue}")
        return 1

    print("Property Setter fixture audit passed.")
    return 0


def parse_property_setter_name(row):
    name = row.get("name") or ""
    property_name = row.get("property")
    doctype_or_field = row.get("doctype_or_field")

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


if __name__ == "__main__":
    raise SystemExit(main())
