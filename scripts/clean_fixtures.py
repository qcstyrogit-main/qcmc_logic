#!/usr/bin/env python3
"""Normalize, fix, and validate fixtures without running export-fixtures."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[1]

STEPS = [
	APP_ROOT / "scripts" / "normalize_fixtures.py",
	APP_ROOT / "scripts" / "fix_fixture_validation_errors.py",
	APP_ROOT / "scripts" / "validate_fixtures.py",
	APP_ROOT / "scripts" / "audit_doctype_fixtures.py",
	APP_ROOT / "scripts" / "audit_property_setters.py",
]


def run_step(script: Path) -> int:
	command = [sys.executable, str(script)]
	print(f"$ {' '.join(command)}", flush=True)
	return subprocess.run(command, cwd=APP_ROOT, check=False).returncode


def main() -> int:
	for script in STEPS:
		exit_code = run_step(script)
		if exit_code:
			return exit_code

	print("Fixture cleanup without export passed.")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
