# Developer Fixture Workflow

This project should use the repository as the source of truth for app metadata.
That means changes should normally be made through code review by editing code,
fixtures, and patches in the repo.

## Short Answer

After a normal repo-based change, run:

```bash
bench --site erp.qcstyro.local migrate
python3 apps/qcmc_logic/scripts/clean_fixtures.py
```

Do not run `bench export-fixtures` after this.

## Why

When a developer or Codex changes metadata in the repo, the fixture JSON files
are changed directly when fixture records need to change.

Examples:

- `qcmc_logic/fixtures/custom_field.json`
- `qcmc_logic/fixtures/doctype.json`
- `qcmc_logic/fixtures/property_setter.json`
- `qcmc_logic/fixtures/report.json`
- `qcmc_logic/fixtures/print_format.json`

Patches are added when an existing site also needs data repair or migration
logic. On `bench migrate`, Frappe runs patches and imports/syncs fixtures into
the site database.

Running `bench export-fixtures` immediately after that is unnecessary and can
be harmful because it may re-export unrelated database state, noisy ordering, or
metadata drift back into the repo.

## Normal Repo-Based Change
## pag si AI (claude or codex) ang nag initiate ng changes na may effect sa GUI (for example ,sinabi ko na mag create xa ng additional fields para sa doctype ko, o kya xa ang inutusan ko na mag fix ng print format na ginalaw nya directly ung printformat.json , pinakamadaling way , tignan nyo kung ang modified ay mga json fixtures)  
Use this when changes were made in code, fixtures, and patches.

```bash
cd /home/qcmc_admin/frappe-bench
bench --site erp.qcstyro.local migrate

cd apps/qcmc_logic
python3 scripts/clean_fixtures.py
git diff
```

Expected result:

- Patches apply to the site.
- Fixtures import into the site.
- Fixture JSON is normalized.
- Fixture validators and audits pass.
- `git diff` shows only intentional repo changes.

## When To Create A Patch

Create a patch when the live database needs a one-time repair or migration that
fixture import alone may not safely handle.

Examples:

- Fixing existing broken DocType metadata.
- Moving a misplaced Property Setter back to the correct DocType.
- Creating or repairing data rows that are not fully handled by fixture import.
- Backfilling a new field.
- Removing stale records.

Register patches in:

```text
qcmc_logic/patches.txt
```

## When To Edit Fixtures Directly

Edit fixtures directly when the fixture record is part of the intended app
metadata.

Examples:

- A report query changes.
- A print format changes.
- A custom field definition changes.
- A property setter target or value changes.
- A custom DocType field list changes.

If a fixture changes and an existing site also needs repair logic, do both:
edit the fixture and add a patch.

## When To Run Export Fixtures

Only run export fixtures when someone intentionally changed fixture-backed
metadata in the Frappe UI and that database change should become repository
source code.

Examples:

- Customize Form changes made in the browser.
- Property Setter changes made in the browser.
- Print Format changes made in the browser.
- Report changes made in the browser.
- Workflow or Workspace changes made in the browser.

Use the wrapper, not raw `bench export-fixtures`:

```bash
cd /home/qcmc_admin/frappe-bench
python3 apps/qcmc_logic/scripts/export_fixtures_clean.py --site erp.qcstyro.local --app qcmc_logic
```

Then review the diff carefully.

## No-Export Fixture Safety Check

Use this after repo-based work, conflict resolution, or manual fixture edits:

```bash
cd /home/qcmc_admin/frappe-bench/apps/qcmc_logic
python3 scripts/clean_fixtures.py
```

This runs:

- `normalize_fixtures.py`
- `fix_fixture_validation_errors.py`
- `validate_fixtures.py`
- `audit_doctype_fixtures.py`
- `audit_property_setters.py`

## Team Rules

- Do not use the Frappe UI for app metadata changes unless the team explicitly
  agrees that the UI change is the source change.
- If the change was made in the repo, do not export fixtures after migration.
- If the change was made in the UI, export fixtures with
  `export_fixtures_clean.py` and review the diff.
- Always run `clean_fixtures.py` before committing fixture changes.
- Always review fixture diffs. Stop if unrelated DocTypes, unrelated modules,
  or large unexpected Property Setter changes appear.
- Install the local pre-commit hook once per clone:

```bash
python3 scripts/install_git_hooks.py
```
