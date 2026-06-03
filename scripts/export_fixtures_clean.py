#!/usr/bin/env python3
"""Export fixtures, normalize them, fix safe validation issues, and validate.

Use this instead of running `bench export-fixtures` directly.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[1]
BENCH_ROOT = APP_ROOT.parents[1]
NORMALIZE_SCRIPT = APP_ROOT / "scripts" / "normalize_fixtures.py"
FIX_SCRIPT = APP_ROOT / "scripts" / "fix_fixture_validation_errors.py"
VALIDATE_SCRIPT = APP_ROOT / "scripts" / "validate_fixtures.py"


def run_step(command: list[str], *, cwd: Path) -> int:
	print(f"$ {' '.join(command)}", flush=True)
	return subprocess.run(command, cwd=cwd, check=False).returncode


def main() -> int:
	parser = argparse.ArgumentParser(
		description="Run bench export-fixtures followed by fixture cleanup and validation."
	)
	parser.add_argument(
		"--skip-export",
		action="store_true",
		help="Only run normalize, fix, and validate. Useful after a manual export.",
	)
	parser.add_argument(
		"--site",
		default=os.environ.get("FRAPPE_SITE"),
		help="Site name to pass to bench export-fixtures. Can also be set with FRAPPE_SITE.",
	)
	parser.add_argument(
		"--app",
		help="Optional app name to pass to bench export-fixtures --app.",
	)
	args = parser.parse_args()

	steps = []
	if not args.skip_export:
		if not args.site:
			parser.error("--site is required unless --skip-export is used")

		export_command = ["bench", "--site", args.site, "export-fixtures"]
		if args.app:
			export_command.extend(["--app", args.app])

		steps.append((export_command, BENCH_ROOT))

	steps.extend(
		[
			([sys.executable, str(NORMALIZE_SCRIPT)], APP_ROOT),
			([sys.executable, str(FIX_SCRIPT)], APP_ROOT),
			([sys.executable, str(VALIDATE_SCRIPT)], APP_ROOT),
		]
	)

	for command, cwd in steps:
		exit_code = run_step(command, cwd=cwd)
		if exit_code:
			return exit_code

	return 0


if __name__ == "__main__":
	raise SystemExit(main())
