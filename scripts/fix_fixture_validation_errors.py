#!/usr/bin/env python3
"""Fix validation errors that can be corrected safely in fixture JSON files.

Run this after `bench export-fixtures` and `normalize_fixtures.py`.
Currently this fixes Custom Field records whose `name` does not match
`{dt}-{fieldname}`, which is the import-breaking issue checked by
`validate_fixtures.py`.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any


APP_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURES_DIR = APP_ROOT / "qcmc_logic" / "fixtures"


def has_conflict_markers(text: str) -> bool:
	return re.search(r"(?m)^(<<<<<<<|=======|>>>>>>>)", text) is not None


def get_fixture_files(fixtures_dir: Path) -> list[Path]:
	return sorted(fixtures_dir.glob("*.json"))


def load_fixture_file(path: Path) -> list[dict[str, Any]]:
	text = path.read_text(encoding="utf-8")
	if has_conflict_markers(text):
		raise ValueError(
			f"{path}: contains Git conflict markers. Run resolve_fixture_conflicts.py first."
		)

	data = json.loads(text)
	if not isinstance(data, list):
		raise ValueError(f"{path}: expected top-level JSON array")

	for index, doc in enumerate(data, start=1):
		if not isinstance(doc, dict):
			raise ValueError(f"{path}:{index}: expected JSON object")

	return data


def collect_custom_field_issues(
	fixture_files: list[Path],
) -> tuple[list[tuple[Path, int, dict[str, Any], str]], list[str]]:
	name_fixes = []
	custom_field_keys = defaultdict(list)
	custom_field_names = defaultdict(list)
	errors = []

	for fixture_file in fixture_files:
		docs = load_fixture_file(fixture_file)
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
				name_fixes.append((fixture_file, index, doc, expected_name))

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

	return name_fixes, errors


def write_json_file(path: Path, docs: list[dict[str, Any]]) -> None:
	path.write_text(json.dumps(docs, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def fix_custom_field_names(fixtures_dir: Path, *, dry_run: bool) -> tuple[int, list[str]]:
	fixture_files = get_fixture_files(fixtures_dir)
	name_fixes, errors = collect_custom_field_issues(fixture_files)
	if errors:
		return 0, errors

	fixes_by_file = defaultdict(list)
	for fixture_file, index, doc, expected_name in name_fixes:
		fixes_by_file[fixture_file].append((index, doc, expected_name))

	for fixture_file, fixes in sorted(fixes_by_file.items()):
		if dry_run:
			continue

		docs = load_fixture_file(fixture_file)
		for index, _doc, expected_name in fixes:
			docs[index - 1]["name"] = expected_name
		write_json_file(fixture_file, docs)

	return len(name_fixes), []


def main() -> int:
	parser = argparse.ArgumentParser(description="Fix safe qcmc_logic fixture validation errors.")
	parser.add_argument(
		"--fixtures-dir",
		type=Path,
		default=DEFAULT_FIXTURES_DIR,
		help=f"Fixture directory to fix. Defaults to {DEFAULT_FIXTURES_DIR}",
	)
	parser.add_argument(
		"--dry-run",
		action="store_true",
		help="Only report Custom Field names that would be fixed.",
	)
	args = parser.parse_args()

	try:
		fixture_files = get_fixture_files(args.fixtures_dir)
		name_fixes, blocking_errors = collect_custom_field_issues(fixture_files)
		if blocking_errors:
			for error in blocking_errors:
				print(error)
			print("Cannot auto-fix missing fields or duplicate Custom Field records.")
			return 1

		for fixture_file, index, doc, expected_name in name_fixes:
			print(f"{fixture_file}:{index}: {doc.get('name')!r} -> {expected_name!r}")

		fix_count, errors = fix_custom_field_names(args.fixtures_dir, dry_run=args.dry_run)
	except (ValueError, json.JSONDecodeError) as error:
		print(error)
		return 1

	if errors:
		for error in errors:
			print(error)
		return 1

	if args.dry_run and name_fixes:
		print(f"{len(name_fixes)} Custom Field name(s) would be fixed.")
	elif fix_count:
		print(f"Fixed {fix_count} Custom Field name(s).")
	else:
		print("No safe fixture validation fixes needed.")

	return 0


if __name__ == "__main__":
	raise SystemExit(main())
