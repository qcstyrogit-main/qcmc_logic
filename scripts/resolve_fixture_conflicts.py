#!/usr/bin/env python3
"""Safely auto-resolve common qcmc_logic fixture merge conflicts.

This script resolves JSON fixture conflicts when both branches changed different
fixture records. It can also merge non-overlapping field-level changes inside
the same fixture record. If both branches changed the same field differently,
it stops and reports the record/field that needs human review.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from normalize_fixtures import normalize_file, normalize_value
from validate_fixtures import DEFAULT_FIXTURES_DIR, validate_custom_fields


APP_ROOT = Path(__file__).resolve().parents[1]


@dataclass
class FixtureVersion:
	docs: list[dict[str, Any]]
	by_key: dict[tuple[Any, ...], dict[str, Any]]
	order: list[tuple[Any, ...]]
	duplicate_warnings: list[str]


ABSENT = object()


def run_git(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
	return subprocess.run(
		["git", "-C", str(APP_ROOT), *args],
		check=check,
		text=True,
		capture_output=True,
	)


def conflicted_fixture_files() -> list[Path]:
	result = run_git(
		["diff", "--name-only", "--diff-filter=U", "--", "qcmc_logic/fixtures/*.json"]
	)
	return [APP_ROOT / line for line in result.stdout.splitlines() if line.strip()]


def read_stage(relative_path: str, stage: int) -> list[dict[str, Any]] | None:
	result = run_git(["show", f":{stage}:{relative_path}"], check=False)
	if result.returncode != 0:
		return None

	data = json.loads(result.stdout)
	if not isinstance(data, list):
		raise ValueError(f"{relative_path}: expected top-level JSON array")

	docs = []
	for index, doc in enumerate(data, start=1):
		if not isinstance(doc, dict):
			raise ValueError(f"{relative_path}:{index}: expected JSON object")
		docs.append(normalize_value(doc))

	return docs


def doc_key(doc: dict[str, Any], index: int) -> tuple[Any, ...]:
	doctype = doc.get("doctype")

	if doctype == "Custom Field" and doc.get("dt") and doc.get("fieldname"):
		return ("Custom Field", doc.get("dt"), doc.get("fieldname"))

	if doctype == "Property Setter" and doc.get("doc_type") and doc.get("field_name") and doc.get("property"):
		return ("Property Setter", doc.get("doc_type"), doc.get("field_name"), doc.get("property"))

	if doctype and doc.get("name"):
		return (doctype, doc.get("name"))

	return ("__unkeyed__", index, json.dumps(doc, sort_keys=True, ensure_ascii=False))


def build_version(docs: list[dict[str, Any]] | None, label: str) -> FixtureVersion:
	if docs is None:
		return FixtureVersion(docs=[], by_key={}, order=[], duplicate_warnings=[])

	by_key = {}
	order = []
	duplicate_warnings = []
	for index, doc in enumerate(docs):
		key = doc_key(doc, index)
		if key in by_key:
			if by_key[key] == doc:
				duplicate_warnings.append(
					f"{label}: collapsed identical duplicate fixture key {format_key(key)}"
				)
				continue

			raise ValueError(f"{label}: duplicate fixture key {format_key(key)} has different data")
		by_key[key] = doc
		order.append(key)

	return FixtureVersion(
		docs=docs,
		by_key=by_key,
		order=order,
		duplicate_warnings=duplicate_warnings,
	)


def format_key(key: tuple[Any, ...]) -> str:
	return " / ".join(str(part) for part in key)


def merge_value(
	base_value: Any,
	ours_value: Any,
	theirs_value: Any,
	location: str,
) -> tuple[Any, list[str]]:
	if ours_value == theirs_value:
		return ours_value, []

	if ours_value == base_value:
		return theirs_value, []
	if theirs_value == base_value:
		return ours_value, []

	if ours_value is ABSENT and theirs_value is ABSENT:
		return ABSENT, []
	if ours_value is ABSENT:
		return ABSENT, [f"ours deleted but theirs changed {location}"]
	if theirs_value is ABSENT:
		return ABSENT, [f"theirs deleted but ours changed {location}"]

	if (
		isinstance(base_value, dict)
		and isinstance(ours_value, dict)
		and isinstance(theirs_value, dict)
	):
		return merge_dict(base_value, ours_value, theirs_value, location)

	if (
		isinstance(base_value, list)
		and isinstance(ours_value, list)
		and isinstance(theirs_value, list)
	):
		return merge_child_list(base_value, ours_value, theirs_value, location)

	return None, [f"both branches changed {location} differently"]


def merge_dict(
	base_doc: dict[str, Any],
	ours_doc: dict[str, Any],
	theirs_doc: dict[str, Any],
	location: str,
) -> tuple[dict[str, Any], list[str]]:
	merged = {}
	conflicts = []

	for fieldname in sorted(set(base_doc) | set(ours_doc) | set(theirs_doc)):
		value, field_conflicts = merge_value(
			base_doc.get(fieldname, ABSENT),
			ours_doc.get(fieldname, ABSENT),
			theirs_doc.get(fieldname, ABSENT),
			f"{location}.{fieldname}",
		)
		conflicts.extend(field_conflicts)
		if value is not ABSENT:
			merged[fieldname] = value

	return merged, conflicts


def merge_child_list(
	base_items: list[Any],
	ours_items: list[Any],
	theirs_items: list[Any],
	location: str,
) -> tuple[list[Any] | None, list[str]]:
	try:
		base = build_version(base_items, f"{location} base")
		ours = build_version(ours_items, f"{location} ours")
		theirs = build_version(theirs_items, f"{location} theirs")
	except ValueError:
		return None, [f"both branches changed unkeyed list {location} differently"]

	return merge_version_maps(base, ours, theirs, location=location)


def merge_doc(
	key: tuple[Any, ...],
	base_doc: dict[str, Any] | None,
	ours_doc: dict[str, Any] | None,
	theirs_doc: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, list[str]]:
	key_label = format_key(key)

	if ours_doc == theirs_doc:
		return ours_doc, []

	if base_doc is None:
		if ours_doc is None:
			return theirs_doc, []
		if theirs_doc is None:
			return ours_doc, []
		return None, [f"both branches added different versions of {key_label}"]

	if ours_doc == base_doc:
		return theirs_doc, []
	if theirs_doc == base_doc:
		return ours_doc, []

	if ours_doc is None and theirs_doc is None:
		return None, []
	if ours_doc is None:
		return None, [f"ours deleted but theirs changed {key_label}"]
	if theirs_doc is None:
		return None, [f"theirs deleted but ours changed {key_label}"]

	return merge_dict(base_doc, ours_doc, theirs_doc, key_label)


def merge_versions(
	base: FixtureVersion,
	ours: FixtureVersion,
	theirs: FixtureVersion,
) -> tuple[list[dict[str, Any]], list[str]]:
	return merge_version_maps(base, ours, theirs, location="")


def merge_version_maps(
	base: FixtureVersion,
	ours: FixtureVersion,
	theirs: FixtureVersion,
	*,
	location: str,
) -> tuple[list[dict[str, Any]], list[str]]:
	merged = []
	conflicts = []
	seen = set()
	ordered_keys = [*ours.order, *theirs.order, *base.order]

	for key in ordered_keys:
		if key in seen:
			continue
		seen.add(key)

		merged_doc, conflict = merge_doc(
			key,
			base.by_key.get(key),
			ours.by_key.get(key),
			theirs.by_key.get(key),
		)
		if conflict:
			conflicts.extend(conflict)
			continue

		if merged_doc is not None:
			merged.append(merged_doc)

	return merged, conflicts


def resolve_file(path: Path, *, dry_run: bool, stage: bool) -> list[str]:
	relative_path = path.relative_to(APP_ROOT).as_posix()
	try:
		base = build_version(read_stage(relative_path, 1), f"{relative_path} base")
		ours = build_version(read_stage(relative_path, 2), f"{relative_path} ours")
		theirs = build_version(read_stage(relative_path, 3), f"{relative_path} theirs")
	except ValueError as error:
		return [f"{relative_path}: {error}"]

	for warning in [*base.duplicate_warnings, *ours.duplicate_warnings, *theirs.duplicate_warnings]:
		print(warning)

	merged, conflicts = merge_versions(base, ours, theirs)
	if conflicts:
		return [f"{relative_path}: {conflict}" for conflict in conflicts]

	if not dry_run:
		path.write_text(json.dumps(merged, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
		normalize_file(path, dry_run=False)
		if stage:
			run_git(["add", relative_path])

	print(f"{'Would resolve' if dry_run else 'Resolved'} {relative_path}")
	return []


def main() -> int:
	parser = argparse.ArgumentParser(description="Safely resolve qcmc_logic JSON fixture conflicts.")
	parser.add_argument(
		"--dry-run",
		action="store_true",
		help="Report what can be resolved without writing files or staging them.",
	)
	parser.add_argument(
		"--no-stage",
		action="store_true",
		help="Write resolved files but do not run git add.",
	)
	args = parser.parse_args()

	files = conflicted_fixture_files()
	if not files:
		print("No conflicted qcmc_logic fixture JSON files found.")
		return 0

	conflicts = []
	for path in files:
		conflicts.extend(resolve_file(path, dry_run=args.dry_run, stage=not args.no_stage))

	if conflicts:
		for conflict in conflicts:
			print(conflict)
		print(f"Stopped with {len(conflicts)} fixture record conflict(s) needing human review.")
		return 1

	if not args.dry_run:
		errors = validate_custom_fields(DEFAULT_FIXTURES_DIR)
		if errors:
			for error in errors:
				print(error)
			print(f"Resolved files, but fixture validation failed with {len(errors)} error(s).")
			return 1

	print("Fixture conflict resolution complete.")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
