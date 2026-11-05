# Management Charts Implementation Plan

> Execute inline with superpowers:executing-plans, test-driven-development and verification-before-completion.

**Goal:** Build the approved interactive management chart builder and printable reporting view.
**Architecture:** A public JavaScript controller consumes selected dashboard scope and Frappe Charts. The existing page module provides authorized trend queries and validated personal chart settings.
**Tech stack:** Installed Frappe/Python/JavaScript/Frappe Charts; no dependencies.
**Spec:** `docs/superpowers/specs/2026-10-30-management-charts-design.md`.

## Global constraints

Keep System Manager access, all-status creation counts, current eligibility and
historical counts. Charts summarize KPI scope independently of Activity View.
Do not create transactions, change account permissions, or install dependencies.
Keep changes uncommitted in the installed app for review and local testing.

## Review focus

- Distinct-user counts and permission denominators when users span modules.
- No pie shares of overlapping user populations or sums of percentage rates.
- Snapshot/filter mismatch in delayed trend responses and printed reports.
- Saved config validation, user isolation, reload and legitimate empty layouts.
- Escaping through Frappe Charts' SVG/HTML tooltip rendering and print markup.

### Task 1: Data endpoints

**Files:** Page `user_transaction_dashboard.py`, backend dashboard tests.
**Interfaces:** `get_creation_trend(date_from,date_to,doctypes=None,users=None,interval="month") -> {labels,values}`; `get_chart_layout() -> {charts: list|null}`; `save_chart_layout(charts) -> {charts}`.

- [x] Add failing trend SQL/scope/boundary/authorization and config/isolation tests.
- [x] Implement validated bucket queries and zero filling, reusing metadata scope.
- [x] Implement whitelist-validated chart definitions in native current-user Page settings.
- [x] Run Bench integration tests until green.

### Task 2: Chart controller and dashboard integration

**Files:** Create `qcmc_logic/public/js/user_transaction_charts.js`, `qcmc_logic/tests/test_user_transaction_charts_ui.js`; modify Page JS and existing UI tests.
**Interfaces:** `frappe.UserTransactionCharts(dashboard)`; `update(scope)`, `clear()`; pure aggregation/validation exposed as `frappe.user_transaction_chart_data` for consumers and tests.

- [x] Write failing Node cases for grouped metrics, distinct users, zero denominators, ranking/Other, config validation, cleanup, stale trends and escaping.
- [x] Implement controller, Add/Edit dialogs, starter charts, saved personal layout, SVG export and printable snapshot with data tables.
- [x] Load script via native version-managed public asset and hook refreshed scope/clear states; keep chart host stable outside rebuilt grid.
- [x] Run all dashboard and chart Node behavior/syntax checks.

### Task 3: Deployment and review

- [x] Update README and run backend regression checks plus current data smoke checks.
- [x] Obtain independent read-only review; address concrete findings and verify fixes.
- [x] Clear site cache; report how to use Add Chart, Save Layout and Print Management Report.

## Verification and review record

- Tests first failed on missing APIs/controller. Five chart API integration tests and all seven existing dashboard integration checks now pass. Expanded chart/controller Node tests and existing dashboard Node tests pass; JavaScript syntax and git whitespace checks pass.
- Actual October site payload: all grouped document chart totals and monthly trend equal 521; overall adoption equals Using 2 / Not Using 336. Chart calculations agree with the full dashboard KPI scope.
- Independent review found two Important issues. Installed AssetManager rejected an explicit query-string version; reproduced against the real installed extension parser, then fixed by using a bare asset URL. Installed charts initially show zero/partial values; added disabled entry animation and a synchronous real-data update before enabling print/export. Regression checks cover rendering readiness.
- Addressed both review minors: SVG labels remain raw text for the native textContent renderer while HTML tooltip values are escaped at tip.setValues; Reset Defaults is guarded until the saved layout loads.
- Browser verification was attempted using existing Cypress/Electron under Xvfb, but startup failed because libnss3.so is absent. No system packages were installed. Browser appearance and print pagination are not visually verified.
- Layout definitions use normal current-user Frappe settings and their native scheduled persistence; transaction data and fixed dates are not stored in the layout.
