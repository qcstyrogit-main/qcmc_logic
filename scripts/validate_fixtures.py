#!/usr/bin/env python3
"""Validate fixture JSON files for common import-breaking mistakes."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


APP_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURES_DIR = APP_ROOT / "qcmc_logic" / "fixtures"


def iter_fixture_docs(fixtures_dir: Path) -> tuple[Path, list[dict[str, Any]]]:
	for fixture_file in sorted(fixtures_dir.glob("*.json")):
		data = json.loads(fixture_file.read_text(encoding="utf-8"))
		if not isinstance(data, list):
			raise ValueError(f"{fixture_file}: expected top-level JSON array")

		docs = []
		for index, doc in enumerate(data, start=1):
			if not isinstance(doc, dict):
				raise ValueError(f"{fixture_file}:{index}: expected JSON object")
			docs.append(doc)

		yield fixture_file, docs


def validate_custom_fields(fixtures_dir: Path) -> list[str]:
	errors = []
	custom_field_keys = defaultdict(list)
	custom_field_names = defaultdict(list)

	for fixture_file, docs in iter_fixture_docs(fixtures_dir):
		for index, doc in enumerate(docs, start=1):
			if doc.get("doctype") != "Custom Field":
				continue

			name = doc.get("name")
			dt = doc.get("dt")
			fieldname = doc.get("fieldname")
			location = f"{fixture_file}:{index}"

			if not name or not dt or not fieldname:
				errors.append(f"{location}: Custom Field must have name, dt, and fieldname")
				continue

			expected_name = f"{dt}-{fieldname}"
			if name != expected_name:
				errors.append(
					f"{location}: Custom Field name mismatch: {name!r} should be {expected_name!r}"
				)

			custom_field_keys[(dt, fieldname)].append(location)
			custom_field_names[name].append(location)

	for (dt, fieldname), locations in sorted(custom_field_keys.items()):
		if len(locations) > 1:
			errors.append(
				f"Duplicate Custom Field target {dt!r}.{fieldname!r} in {', '.join(locations)}"
			)

	for name, locations in sorted(custom_field_names.items()):
		if len(locations) > 1:
			errors.append(f"Duplicate Custom Field name {name!r} in {', '.join(locations)}")

	return errors


def main() -> int:
	parser = argparse.ArgumentParser(description="Validate qcmc_logic fixture JSON files.")
	parser.add_argument(
		"--fixtures-dir",
		type=Path,
		default=DEFAULT_FIXTURES_DIR,
		help=f"Fixture directory to validate. Defaults to {DEFAULT_FIXTURES_DIR}",
	)
	args = parser.parse_args()

	errors = validate_custom_fields(args.fixtures_dir)
	if errors:
		for error in errors:
			print(error)
		print(f"Fixture validation failed with {len(errors)} error(s).")
		return 1

	print("Fixture validation passed.")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
