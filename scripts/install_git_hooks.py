#!/usr/bin/env python3
"""Install qcmc_logic local Git hooks."""

from __future__ import annotations

import os
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[1]
HOOKS_DIR = APP_ROOT / ".git" / "hooks"
PRE_COMMIT = HOOKS_DIR / "pre-commit"

PRE_COMMIT_CONTENT = f"""#!/bin/sh
set -eu

cd {APP_ROOT}
python3 scripts/validate_fixtures.py
python3 scripts/audit_doctype_fixtures.py
"""


def main() -> int:
	HOOKS_DIR.mkdir(parents=True, exist_ok=True)
	PRE_COMMIT.write_text(PRE_COMMIT_CONTENT, encoding="utf-8")
	os.chmod(PRE_COMMIT, 0o755)
	print(f"Installed {PRE_COMMIT}")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
