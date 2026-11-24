# Delivery Scheduling checkpoint

Consolidated November 23, 2026. [Agreed workflow](delivery_scheduling_architecture_v2.md) is the current functional reference.

## Implemented source

- One standalone schedule ledger and movement history.
- Regular-only eligibility and lazy initialization for unscheduled SO Items.
- Logistics autosave, reason restrictions, optional free-text Logistics remarks, and queue exclusion after DN creation or full transfer.
- Sales Draft DN preview, bounded quantities, remainder conservation, and consolidation.
- Two operational workbenches, retired navigation, daily summary cards, and Sales Order editor usability improvements.
- DR assignment, Frappe workflow release, optional draft invoice preview, and QC invoice format selection.

## Accepted earlier evidence

The owner accepted 161 earlier isolated regressions and persisted scheduling, multi-item Draft DN consolidation, deletion/allocation release, short delivery, duplicate/concurrent Proceed, Invoicing Clerk assignment, and Draft-to-To Deliver and Bill workflow release. These precede subsequent UI and eligibility changes.

Later focused runs passed 36 scheduling tests. Syntax and whitespace checks passed for subsequent edits. These checks do not establish coverage of the latest whole workflow.

Development SO 26-00027 received five owner-confirmed baseline corrections. Records were reloaded after commit. The November 18 row has Original Qty 200, Changes −100, Total 100. Audit records identify the correction as recorded at correction time. The SO document comparison remained identical.

## Outstanding gates

| Gate | Status | Required evidence |
|---|---|---|
| Latest editor, reason restrictions, autosave, queue removal and cards | NOT RUN | Authenticated browser interactions |
| Regular-only lazy schedule creation and transfer | NOT RUN | Persisted role-based tests, retries, SO amount comparisons |
| Latest printing preview and QC invoice format | NOT RUN | Actual print preview and linked draft invoice checks |
| DR number concurrent uniqueness | OPEN | Transaction-safe serialization or database constraint plus concurrency test |
| Large queues and authoritative totals | OPEN | Pagination or complete totals beyond query caps |
| Submitted DN cancellation / actual delivery OTIF | BLOCKED | Separate stock-posting authorization or trustworthy submitted data |
| MPS | NOT RUN | Business usage decision and compatibility if applicable |

Shared Playwright is under /home/qcmc_admin/browser-automation. A previous runner attempt failed at Chromium launch with missing libnspr4.so. Recheck the environment before assuming that failure still applies. Keep sessions and browser artifacts outside the app repository.

Production deployment, stock/accounting posting, and historical migration require their respective authorization.

## Cleanup

Removed retired Query Report / old workbench frontend tests and the obsolete SO Item-splitting plan. Consolidated report-dependency, collaboration, and old confirmation-fix documents into the workflow reference.

Retain current service, financial integrity, lifecycle, and concurrency tests. The old split test file now retains seven active locking and financial guard tests. Removed retired SO Item-splitting operation tests, the obsolete split-total suite, the inactive DN-based frontend autosave suite, and four obsolete UI source-string architecture tests. The retained locking and architecture suites passed 14 tests after cleanup.

The SQL reporting reference remains a technical read-only investigation aid. The manual acceptance guide is the current browser and persisted-record checklist.
