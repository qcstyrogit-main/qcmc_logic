## QCMC Logics

Company Business Rules and Logics

### Fixture Workflow

Use the wrapper instead of running `bench export-fixtures` directly:

```bash
python3 apps/qcmc_logic/scripts/export_fixtures_clean.py
git diff
```

This runs `bench export-fixtures`, normalizes exported JSON, fixes safe validation
issues, and validates the result.

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
git diff
```

`normalize_fixtures.py` removes volatile metadata such as timestamps, owners, and
assignment tags so timestamp-only fixture exports do not create noisy diffs.

`fix_fixture_validation_errors.py` fixes safe validation errors, currently
`Custom Field` records whose `name` does not match `{dt}-{fieldname}`.

`validate_fixtures.py` catches import-breaking `Custom Field` mistakes, including
records whose `name` does not match `{dt}-{fieldname}`.

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

#### License

mit
