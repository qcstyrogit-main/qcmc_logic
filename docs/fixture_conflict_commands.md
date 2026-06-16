# Fixture Conflict Commands

Use this when `git status` shows a conflict in `qcmc_logic/fixtures/doctype.json`
or another fixture file.

## 1. Check Conflict State

```bash
cd /home/qcmc_admin/frappe-bench/apps/qcmc_logic
git status --short
git diff --name-only --diff-filter=U
```

Shows which files are still unresolved. `UU` means Git still sees a conflict.

## 2. Find Conflict Markers

```bash
rg -n '^(<<<<<<<|=======|>>>>>>>)' qcmc_logic/fixtures/doctype.json
```

Shows exact lines with conflict markers. If this prints nothing, the file no
longer contains visible conflict markers.

## 3. Try Safe Fixture Resolver

```bash
python3 scripts/resolve_fixture_conflicts.py
```

Use this first for JSON fixture conflicts. It auto-resolves safe cases where
both branches changed different fixture records. If both branches changed the
same record differently, it stops and tells you what needs manual review.

## 4. Validate JSON

```bash
python3 -m json.tool qcmc_logic/fixtures/doctype.json >/tmp/doctype_check
```

Checks that `doctype.json` is valid JSON after resolving conflict markers.

## 5. Validate Fixtures

```bash
python3 scripts/validate_fixtures.py
python3 scripts/audit_doctype_fixtures.py
```

`validate_fixtures.py` catches import-breaking fixture mistakes.

`audit_doctype_fixtures.py` catches DocType ownership mix-ups and duplicate
DocField names, such as an LMS or ZKTeco DocType accidentally exported by
`qcmc_logic`.

## 6. Check Whitespace And Mark Resolved

```bash
git diff --check
git add qcmc_logic/fixtures/doctype.json
git status --short
```

`git diff --check` catches leftover conflict markers and whitespace errors.

`git add` marks the file as resolved. After this, the file should no longer show
as `UU`.

## 7. Full Fixture Safety Check

```bash
python3 scripts/export_fixtures_clean.py --skip-export
```

Runs normalize, safe fixes, fixture validation, and DocType audit without
running `bench export-fixtures` again.

## 8. Before Commit

```bash
.git/hooks/pre-commit
git status --short
```

Runs the same fixture checks that the local pre-commit hook will run.

If the hook is not installed yet:

```bash
python3 scripts/install_git_hooks.py
```
