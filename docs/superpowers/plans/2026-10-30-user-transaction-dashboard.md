# User Transaction Dashboard Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans in this session. Steps use checkbox syntax for tracking.

**Goal:** Build the approved ERPNext dashboard with inclusive creation dates and user by DocType counts.

**Architecture:** A standard QCMC Logics Desk Page serves a dynamic matrix and three summary cards. A read-only whitelisted endpoint aggregates transactions by owner with the Frappe query builder and enforces System Manager access.

**Tech Stack:** Existing Frappe Python, JavaScript, CSS, unittest and Node; no dependencies.

**Spec:** `docs/superpowers/specs/2026-10-30-user-transaction-dashboard-design.md`

## Global Constraints

- Count all statuses using owner and creation; include the entire final day.
- Restrict Page and endpoint to System Manager; preserve existing reports.
- Include zero-activity users and eligible DocTypes; exclude child, Single, virtual and non-submittable DocTypes.
- Escape dynamic text and discard stale responses.
- Work in the installed app checkout so local Bench can load the new Page. Leave changes uncommitted for review.

## Review Focus

- Date boundaries and invalid/missing ranges must not silently broaden counts.
- Duplicate Employee links must not duplicate counts; users without links need a name fallback.
- Duplicate full names need distinct user identifiers.
- Old successful or failed responses must not replace newer filter results.
- HTML in names or DocType labels must render as text.

### Task 1: Authorized aggregation endpoint

**Files:** Create `qcmc_logic/qcmc_logics/page/user_transaction_dashboard/__init__.py`, `user_transaction_dashboard.py`, `user_transaction_dashboard.json`; create `qcmc_logic/tests/test_user_transaction_dashboard.py`.

**Interfaces:** `get_data(date_from=None, date_to=None)` returns `doctypes: list[str]`, `rows: list[{user, employee_name, counts, total}]`, `totals: {counts, total}`, `summary: {documents, active_users, active_doctypes}`.

- [x] Write tests for authorization, date validation, independent database counts, zero data, and employee-name deduplication/fallback.
- [x] Run tests with Bench; observe the missing endpoint failure.
- [x] Implement validated date bounds, grouped owner queries, employee labels, totals and Page metadata.
- [x] Run `bench --site erp.qcstyro.local execute qcmc_logic.tests.test_user_transaction_dashboard.run_tests`; expect all checks passing.

### Task 2: Dashboard interface

**Files:** Create `qcmc_logic/qcmc_logics/page/user_transaction_dashboard/user_transaction_dashboard.js`; create `qcmc_logic/tests/test_user_transaction_dashboard_ui.js`; update `README.md`.

**Interfaces:** Consume Task 1 payload using `frappe.call`; register `frappe.pages["user-transaction-dashboard"].on_page_load`.

- [x] Write Node behavior tests for matrix escaping/totals, stale responses and validation/error/empty states; observe failure before implementation.
- [x] Implement date controls, Refresh action, responsive summary cards, accessible matrix with sticky names/header, and loading/error/empty states.
- [x] Run `node qcmc_logic/tests/test_user_transaction_dashboard_ui.js` and `node --check qcmc_logic/qcmc_logics/page/user_transaction_dashboard/user_transaction_dashboard.js`; expect success.
- [x] Document route, scope and access in README.

### Task 3: Local sync and review

- [x] Sync only the new Page with `bench --site erp.qcstyro.local reload-doc qcmc_logics page user_transaction_dashboard` and clear its cache.
- [x] Re-run backend and UI tests; independently verify Page roles, generated script and dashboard response through Bench.
- [x] Review the full change for access, query bounds, name handling, stale responses, layout and deployment requirements.
- [x] Report the dashboard route, checks passed, and any browser verification limitation.

## Progress and decisions

- User approved the design with “go”; implement inline without another approval round.
- Use the installed checkout, with no branch changes, dependency installation, commits, or broad migration.
- Tasks 1–3 implemented and synced. Backend tests first failed on missing endpoint, then passed; UI tests first failed on missing script, then passed.
- Independent review found omitted historical owners with deleted accounts. A regression using real transaction queries and missing account metadata reproduced the count loss; fallback owner rows correct it.
- Preserve historical owners in counts even if the current User record is absent, extending the original activity report's behavior to keep dashboard totals complete.
- Initial standalone announcement tests lacked an initialized Frappe site (three errors); the same six baseline tests passed through Bench. All dashboard integration checks use Bench.

- Final verification: six backend integration checks passed, UI behavior checks and JavaScript syntax passed, and Page script loaded through the actual Desk loader. No interactive browser was available for a visual check.

## Follow-up: visible filters and display selection

- [x] Trace hidden dates: replacing `page.main` removed its `.page-form` while the Page retained a detached reference. Preserve native content and mount labeled controls directly in the dashboard.
- [x] Add Modules, Displayed DocTypes and Displayed Users searchable multi-selects; expose the authorized DocType-to-module map in the existing endpoint.
- [x] Add a per-column search row; support names, IDs, count text and numeric comparisons. Keep header inputs mounted while typing, and recompute displayed-scope cards and totals.
- [x] Verify regression tests fail before adding module metadata and filter computation, then pass after implementation.
- [x] Address review findings with failing tests first: explicitly apply Date defaults for raw Frappe controls; escape native MultiSelectList status fallback values, including selected values absent from current options.
- [x] Run all six backend integration checks, expanded Node UI checks, JavaScript syntax and whitespace checks; clear site cache.
- Independent review found no other concrete issues. No interactive visual browser check was performed.
