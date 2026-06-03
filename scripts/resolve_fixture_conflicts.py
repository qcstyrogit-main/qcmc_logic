#!/usr/bin/env python3
"""Safely auto-resolve common qcmc_logic fixture merge conflicts.

This script resolves JSON fixture conflicts when both branches changed different
fixture records. If both branches changed the same record differently, it stops
and reports the record that needs human review.
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


def merge_doc(
	key: tuple[Any, ...],
	base_doc: dict[str, Any] | None,
	ours_doc: dict[str, Any] | None,
	theirs_doc: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, str | None]:
	if ours_doc == theirs_doc:
		return ours_doc, None

	if base_doc is None:
		if ours_doc is None:
			return theirs_doc, None
		if theirs_doc is None:
			return ours_doc, None
		return None, f"both branches added different versions of {format_key(key)}"

	if ours_doc == base_doc:
		return theirs_doc, None
	if theirs_doc == base_doc:
		return ours_doc, None

	if ours_doc is None and theirs_doc is None:
		return None, None
	if ours_doc is None:
		return None, f"ours deleted but theirs changed {format_key(key)}"
	if theirs_doc is None:
		return None, f"theirs deleted but ours changed {format_key(key)}"

	return None, f"both branches changed {format_key(key)} differently"


def merge_versions(
	base: FixtureVersion,
	ours: FixtureVersion,
	theirs: FixtureVersion,
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
			conflicts.append(conflict)
			continue

		if merged_doc is not None:
			merged.append(merged_doc)

	return merged, conflicts


def resolve_file(path: Path, *, dry_run: bool) -> list[str]:
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
	args = parser.parse_args()

	files = conflicted_fixture_files()
	if not files:
		print("No conflicted qcmc_logic fixture JSON files found.")
		return 0

	conflicts = []
	for path in files:
		conflicts.extend(resolve_file(path, dry_run=args.dry_run))

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
