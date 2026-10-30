# User Usage Monitoring Implementation Plan

> Execute inline using superpowers:executing-plans. The user confirmed “Created” after the proposed usage design; continue with that definition.

**Goal:** Compare current Create access with documents created in the selected period.
**Spec:** User-approved proposal in chat, extending `docs/superpowers/specs/2026-10-30-user-transaction-dashboard-design.md`.
**Architecture:** Extend existing read-only endpoint with account state and current Create-permission lists. Filter and summarize in the existing Page without new dependencies or permission changes.

## Decisions

- Eligible users are enabled System Users with current DocType-level Create permission in the selected module/DocType scope. Respect effective role permissions, including custom DocPerm and owner-only Create grants. This is not a simulation of every document's warehouse/company validation.
- Preserve historical counts, including former users and changed permissions. Such rows may appear with activity but are labeled Historical activity when not currently eligible; exclude them from the eligible-user denominator.
- Use all selected DocTypes to determine eligibility before hiding zero-activity columns.
- Activity View: With Activity (default), Without Activity, All. With Activity hides empty columns unless individual DocTypes were explicitly selected. Other views expose permission-relevant zero columns.
- Cards: Using, Not Using, Usage Rate, Total Transactions. Cards summarize the selected date/module/DocType/user scope before the Activity View filter so Not Using remains meaningful in the default view. Table footer totals describe the displayed rows.
- Cells: count when positive; 0 when eligible for Create; dash when no current Create access. Retain positive historical counts with a title explaining absent current access.
- Automatically fetch the current month on initialization and avoid duplicate initial requests on page-show. Preserve existing selectors, errors and stale-response handling; keep header search row removed.
- Keep System Manager access and inclusive creation-date semantics unchanged.

## Tasks

- [x] Backend tests first: verify current Create access against Frappe for real users, disabled/website exclusions, owner-only/custom permissions, and historical preservation. Extend endpoint with `enabled`, `user_type`, `monitored`, `can_create` per row, grouping users by effective roles for efficient evaluation.
- [x] UI tests first: current-month automatic load, default activity-only rows/columns, all/inactive views, invariant eligibility cards, selection-scope totals, zero vs dash and historical counts.
- [x] Implement view control, permission-aware grid/status, cards, scoped summary and helpful empty states; update README.
- [x] Run backend integration checks, Node UI tests, syntax and whitespace checks; request independent review and fix concrete findings; clear site cache.

## Review focus

Permission-only zero columns must remain part of the inactivity denominator. Empty periods must show Not Using counts with an empty default grid. Disabled, website and deleted users must not inflate eligible counts. Changing view must not hide the opposite card's population. Positive historical counts must never be lost.

## Verification

- Seven backend integration checks passed, including independently compared SQL counts, current Frappe Create permissions for real users, account-state eligibility, access control and historical owner retention.
- Expanded Node checks passed: automatic dates/load, no duplicate initial fetch, all activity views, full-scope inactivity denominator, permission cells, empty periods, historical counts and stale responses. JavaScript syntax and whitespace checks passed.
- Independent code review found no Critical/Important issues. README feedback was addressed.
- Actual October site payload through frontend filter logic: 521 transactions, 2 Using, 336 Not Using, 338 eligible, 0.6% usage; default grid 2 users/14 DocTypes, inactive view 336 users. All-view footer preserved all 521 transactions.
- Site cache cleared. No interactive visual browser check was performed.
