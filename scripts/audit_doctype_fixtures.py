#!/usr/bin/env python3
"""Audit DocType fixtures for cross-app ownership and mixed child-table fields."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


APP_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DOCTYPE_FIXTURE = APP_ROOT / "qcmc_logic" / "fixtures" / "doctype.json"
ALLOWED_CUSTOM_DOCTYPE_MODULES = {
	"Accounts",
	"Assets",
	"Buying",
	"Custom",
	"HR",
	"Payroll",
	"QCMC Logics",
	"Stock",
}


def load_doctypes(path: Path) -> list[dict[str, Any]]:
	data = json.loads(path.read_text(encoding="utf-8"))
	if not isinstance(data, list):
		raise ValueError(f"{path}: expected top-level JSON array")
	return data


def audit_doctypes(path: Path) -> list[str]:
	errors = []

	for doctype in load_doctypes(path):
		name = doctype.get("name")
		module = doctype.get("module")

		if doctype.get("custom") and module not in ALLOWED_CUSTOM_DOCTYPE_MODULES:
			errors.append(f"{name}: custom DocType belongs to unexpected module {module!r}")

		fieldnames = [field.get("fieldname") for field in doctype.get("fields", [])]
		duplicates = sorted(
			fieldname for fieldname, count in Counter(fieldnames).items() if fieldname and count > 1
		)
		if duplicates:
			errors.append(f"{name}: duplicate fieldname(s): {', '.join(duplicates)}")

	return errors


def main() -> int:
	parser = argparse.ArgumentParser(description="Audit qcmc_logic DocType fixtures.")
	parser.add_argument(
		"--doctype-fixture",
		type=Path,
		default=DEFAULT_DOCTYPE_FIXTURE,
		help=f"DocType fixture path. Defaults to {DEFAULT_DOCTYPE_FIXTURE}",
	)
	args = parser.parse_args()

	try:
		errors = audit_doctypes(args.doctype_fixture)
	except (ValueError, json.JSONDecodeError) as error:
		print(error)
		return 1

	if errors:
		print("DocType fixture audit failed:")
		for error in errors:
			print(f"- {error}")
		return 1

	print("DocType fixture audit passed.")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
