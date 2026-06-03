#!/usr/bin/env python3
"""Remove volatile metadata from fixture JSON files.

Run this after `bench export-fixtures` so Git diffs show meaningful fixture
changes instead of timestamp churn.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


APP_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURES_DIR = APP_ROOT / "qcmc_logic" / "fixtures"
VOLATILE_KEYS = {
	"creation",
	"modified",
	"modified_by",
	"owner",
	"_user_tags",
	"_comments",
	"_assign",
	"_liked_by",
}


def normalize_value(value: Any) -> Any:
	if isinstance(value, dict):
		return {
			key: normalize_value(child_value)
			for key, child_value in value.items()
			if key not in VOLATILE_KEYS
		}

	if isinstance(value, list):
		return [normalize_value(item) for item in value]

	return value


def normalize_file(path: Path, *, dry_run: bool) -> bool:
	original_text = path.read_text(encoding="utf-8")
	data = json.loads(original_text)
	normalized = normalize_value(data)
	normalized_text = json.dumps(normalized, indent=1, ensure_ascii=False) + "\n"

	if normalized_text == original_text:
		return False

	if not dry_run:
		path.write_text(normalized_text, encoding="utf-8")

	return True


def get_fixture_files(fixtures_dir: Path) -> list[Path]:
	return sorted(fixtures_dir.glob("*.json"))


def main() -> int:
	parser = argparse.ArgumentParser(description="Normalize qcmc_logic fixture JSON files.")
	parser.add_argument(
		"--fixtures-dir",
		type=Path,
		default=DEFAULT_FIXTURES_DIR,
		help=f"Fixture directory to normalize. Defaults to {DEFAULT_FIXTURES_DIR}",
	)
	parser.add_argument(
		"--dry-run",
		action="store_true",
		help="Only report files that would change.",
	)
	args = parser.parse_args()

	changed_files = []
	for fixture_file in get_fixture_files(args.fixtures_dir):
		if normalize_file(fixture_file, dry_run=args.dry_run):
			changed_files.append(fixture_file)

	for fixture_file in changed_files:
		print(fixture_file)

	if args.dry_run and changed_files:
		print(f"{len(changed_files)} fixture file(s) would be normalized.")
	elif changed_files:
		print(f"Normalized {len(changed_files)} fixture file(s).")
	else:
		print("Fixtures already normalized.")

	return 0


if __name__ == "__main__":
	raise SystemExit(main())
