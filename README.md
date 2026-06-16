## QCMC Logics

Company Business Rules and Logics

### Fixture Workflow

Use the wrapper instead of running `bench export-fixtures` directly:

```bash
python3 apps/qcmc_logic/scripts/export_fixtures_clean.py --site erp.qcstyro.local
git diff
```

This runs `bench export-fixtures`, normalizes exported JSON, fixes safe validation
issues, and validates the result.

To export only this app's fixtures, add `--app qcmc_logic`:

```bash
python3 apps/qcmc_logic/scripts/export_fixtures_clean.py --site erp.qcstyro.local --app qcmc_logic
```

If you already ran `bench export-fixtures` manually, use:

```bash
python3 apps/qcmc_logic/scripts/export_fixtures_clean.py --skip-export
git diff
```

The manual order is:

```bash
bench export-fixtures
python3 apps/qcmc_logic/scripts/normalize_fixtures.py
python3 apps/qcmc_logic/scripts/fix_fixture_validation_errors.py
python3 apps/qcmc_logic/scripts/validate_fixtures.py
python3 apps/qcmc_logic/scripts/audit_doctype_fixtures.py
git diff
```

`normalize_fixtures.py` removes volatile metadata such as timestamps, owners,
assignment tags, and DocType migration hashes, then sorts top-level fixture
records by stable identity so timestamp-only, migration-hash-only, and
order-only fixture exports do not create noisy diffs. After normalization, it
prints a warning when meaningful fixture changes remain.

`fix_fixture_validation_errors.py` fixes safe validation errors, currently
`Custom Field` records whose `name` does not match `{dt}-{fieldname}`.

`validate_fixtures.py` catches import-breaking `Custom Field` mistakes, including
records whose `name` does not match `{dt}-{fieldname}`.

`audit_doctype_fixtures.py` catches custom DocTypes from unexpected app modules
and duplicate DocField names inside exported DocType fixtures. This prevents
cross-app fixture ownership problems, such as LMS or ZKTeco DocTypes being
exported by qcmc_logic, and catches child-table field mix-ups before migration.

When reviewing `qcmc_logic/fixtures/doctype.json`, stop if an unrelated module
appears. One app should own each custom DocType fixture.

Install the local pre-commit hook once per clone:

```bash
python3 apps/qcmc_logic/scripts/install_git_hooks.py
```

The hook runs `validate_fixtures.py` and `audit_doctype_fixtures.py` before each
commit.

### Fixture Merge Conflicts

When `git pull --rebase` or merge reports conflicts in `qcmc_logic/fixtures/*.json`,
try the safe fixture resolver:

```bash
python3 apps/qcmc_logic/scripts/resolve_fixture_conflicts.py
python3 apps/qcmc_logic/scripts/validate_fixtures.py
git diff
```

The resolver auto-merges only safe JSON fixture cases, such as both branches
changing different fixture records. If both branches changed the same fixture
record differently, it stops and prints the exact record that needs human review.

See `docs/fixture_conflict_commands.md` for the full command runbook and what
each command is for.

#### License

mit
### For faster export fixtures 
```bash
alias export-fixtures='python3 apps/qcmc_logic/scripts/export_fixtures_clean.py'
```
usage: export_fixtures_clean.py [-h] [--skip-export] [--site SITE] [--app APP]

```bash
export-fixtures --site erp.qcstyro.local 
```
