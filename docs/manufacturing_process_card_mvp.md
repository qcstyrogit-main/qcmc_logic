# Manufacturing Process Card MVP

## Status and scope

This is a source-level MVP integration for Production, QA, and Maintenance in `qcmc_logic`. It adds no React UI, new Employee or Workstation master, production stock posting, or new production-output DocType. It does not modify the existing Process Card Workbench or Production Floor Navigator UI.

The existing source foundation already contains the Process Card and Process Card Job DocTypes, shift metadata and status transitions, explicit Job Card assignments, and APIs that store production checkpoints on native Job Card Time Log rows. This change integrates the existing native Downtime Entry, Asset Repair, Quality Inspection, and Job Card participation records with that foundation.

No fixture synchronization, migration, production-data mutation, deployment, or commit was performed. The fixture-backed fields described below must be installed in an authorized test/site rollout before users can use the completed forms.

## Source-level integration gap report

| Area | Existing source and gap | MVP integration |
|---|---|---|
| Process Card | Existing shift and workstation context and Job Card child table; Job Card eligibility needed exact Work Order Operation validation. | Enforces active submitted Work Orders for new assignments, exact operation membership where operations exist, Company/Workstation matching, and non-overlapping shift windows. Historical cards remain readable/reviewable after their Work Order or Job Card completes; new output/participation is blocked on completed work. |
| Production output | Existing native Job Card Time Log checkpoint path and correction history; standard Job Card form had no direct entry action, and Work Order operation limits were not enforced at output save/correction. | Adds standard-form declaration, correction and confirmation. Confirmed good quantity contributes to upstream availability and native manufacturing progress. |
| Manpower | Job Card Time Logs are native and separate from HRMS Attendance, but needed Process Card, pay-mode, and approval-reference context and participation validation. HRMS Shift Assignment is not manufacturing participation. | Uses the same native child table for participation; validates employee, company, shift bounds, pay mode, and employee interval overlaps across linked Job Cards. HRMS Attendance is not changed. |
| Downtime | Native Downtime Entry already records Workstation, operator, reason, and interval, but lacked Process Card/Job Card context. | Adds links and validates Workstation, shift bounds, operator, optional Job Card membership, duration, and same-Process-Card overlap. |
| QA | Native Quality Inspection supports in-process inspections/readings, but lacked Process Card/output references and QA rejection quantities/reasons. | Adds links and reading fields; enforces Job Card/item context and keeps QA findings separate from production-declared rejects. QA rejection quantities require a unique linked output interval and cannot exceed its recorded quantity. |
| Maintenance | Native Asset Repair already records asset, failure/completion, status, and repair actions, but lacked Process Card/Workstation/Job Card context. | Adds context fields and validation. Breakdown duration is not automatically treated as downtime. |
| Machine reporting | Workstation has its own status; no verified Workstation-to-Asset master mapping or authoritative run-hour event source was found. | Summary availability uses Downtime Entry events; reported actual run hours use positive-output intervals. Definitions and source events are returned with the summary. |
| Shared services | Several document services existed, but the department transactions were not consistently linked or exposed in one shift summary. | Adds a participation service and a consolidated, permission-checked shift summary. Native Frappe document APIs remain the write path for QI, Downtime Entry, and Asset Repair. |

## Minimum DocType and field changes

No new master or transaction DocType is required. `Process Card` and `Process Card Job` remain the shift context and Job Card association.

Fixture-backed fields:

- **Job Card Time Log:** Process Card link for participation; DR/PCR pay mode; MCA approval reference; hidden operational good/rejected quantities, entry actor/time, revision, and correction history.
- **Downtime Entry:** Process Card and optional Job Card links.
- **Asset Repair:** Workstation, Process Card, and optional Job Card links; breakdown nature/action requirements are applied when the record is linked to a Process Card.
- **Quality Inspection:** Process Card and optional production output Time Log links.
- **Quality Inspection Reading:** QA rejected quantity, reject reason, and measurement UOM.
- **Shift Type:** configurable default checkpoint interval (120 minutes).

Production quantities remain on native Job Card Time Log rows. A declaration has zero native completed quantity. Production confirmation sets the same row’s native quantity to the declared good quantity and records the confirmer and timestamp. Confirmation advances native manufacturing progress and creates no ledger posting. Per-operation total output (good plus rejected) is capped at the Work Order quantity; each downstream operation is capped at the preceding operation's accepted good quantity. Participation rows use employee/time fields on the same child table and are not counted as production output. Direct edits/removals of output checkpoint values, intervals, or rows are blocked outside the audited correction API.

## Encoding and review processes

### Standard Desk walkthrough

1. **Create the shift:** Open a new Process Card. Select Company, Site, Workstation, shift date/type, actual shift start/end, and one or more eligible Job Cards in the child table. Save. Work Order operation and company/workstation mismatches are rejected server-side.
2. **Start the shift:** On the saved Process Card, use **Shift → Start Shift**. The status controls are permission-checked by the backend.
3. **Record production:** Open each linked Job Card. Use **Record Production Output** to enter the actual interval, good quantity, rejected quantity, and remarks. Reporting intervals are user-selected and may be shorter or longer than the Shift Type checkpoint interval. Repeat for each interval. Use **Correct Production Output** when a declaration needs revision. Use **Production → Confirm Production Output** to select and confirm a validated interval. A confirmed interval retains its source and quantities. Production rejects and QA findings remain separate.
4. **Record participation:** In the Job Card Time Logs child table, enter Employee, Time In/Out, Process Card, DR/PCR Pay Mode, and MCA approval reference when required by company policy. Save the Job Card. To represent a transfer, close the previous employee interval and add the employee's next interval on the receiving Job Card. Participation rows cannot be added, changed, or removed while the Process Card is For Approval, Approved, or Cancelled; unchanged rows remain readable. Do not encode participation in HRMS Attendance.
5. **Record QA:** Create a standard Quality Inspection with Inspection Type **In Process**, Reference Type **Job Card**, the linked Job Card, and Process Card. Enter the inspection result and native reading values; add measurement UOM for product weights. Enter QA Start and QA End for the actual inspection window. QA reporting can span multiple production intervals or cover part of one. Enter the quantity and reason on each rejected reading.
6. **Record downtime:** Create a standard Downtime Entry with Workstation, Process Card, optional linked Job Card, operator, interval, stop reason, and remarks. The interval must be inside the shift and cannot overlap another downtime interval on that Process Card.
7. **Record a breakdown:** Create a standard Asset Repair with Asset, Workstation, Process Card, optional Job Card, failure date, breakdown class/nature, and repair status. Add repair actions before marking it Completed. Asset Repair repair duration is not automatically recorded as Downtime Entry.
8. **Review the shift:** On the Process Card, use **Shift → Shift Summary**. The permission-checked summary shows production, participation, inspections/measurements, QA rejects, downtime, breakdowns, availability, and run-hour metrics. Submit the Process Card for approval when encoding is complete; only Manufacturing Manager/System Manager may approve it.

### Representative 12-hour shift

For a 06:00–18:00 shift, create one Process Card and associate the eligible Job Cards for the Workstation. Record multiple production intervals for each Job Card (for example 06:00–08:00 and 08:00–10:00); the service does not require the intervals to match generated slots. Record employee intervals and transfers, add in-process inspections and weight readings, classify QA findings without changing production quantities, add a downtime interval, and record its related Asset Repair. Use Shift Summary to review the combined records before approval.

The scenario above is a Desk walkthrough, not a claim that a live 12-hour shift or a database-backed end-to-end test was executed.

## Finished goods receipt and Work Order history

On the final-operation Job Card, open **Create → Manufacture Receipt**, enter the actual quantity received and create the draft. Warehouse can also select the final Job Card from the existing Stock Entry form or use scanner receiving. Drafts reserve confirmed output across the order. Each receipt records the exact Process Card, native Time Log and stock quantity for each interval. Allocation starts with the earliest available interval and retains the existing draft allocations during quantity edits. Cancelling a submitted receipt reverses stock and releases its interval quantities. A historical receipt with missing allocation evidence requires reconciliation before using its source for new receipts.

Submit the draft from the standard Stock Entry form to post inventory. On the Work Order, open **View → Manufacturing History** to review operation totals, Process Cards, output intervals, participation, QA, downtime, repairs and submitted stock movements with their production allocations. For a successive shift, submit the first Job Cards after confirming all declarations, then use **Create Next Job Card** to select an operation with remaining production.

## Shared API inventory

All custom methods are non-guest Frappe whitelisted methods unless noted otherwise. Standard document insert/save APIs retain Frappe lifecycle validation and are the write path for the native transaction DocTypes.

| Capability | Method |
|---|---|
| Process Card create and eligible-Job-Card context | `qcmc_logic.api.process_card_workbench.create_process_card`, `get_process_card_creation_context` |
| Process Card retrieval and eligible assignments | `get_process_card_context`, `search_eligible_job_cards`, `add_job_cards`, `remove_job_card`, `transition_status` in `qcmc_logic.api.process_card_workbench` |
| Production output and correction | `qcmc_logic.api.job_card_time_log.save_process_card_output`, `save_process_card_output_batch`, `correct_process_card_output`, `get_process_card_output_entries` |
| Output calculation helper | `qcmc_logic.api.process_card_workbench.calculate_output_metrics` |
| Manpower participation | `qcmc_logic.api.process_card_services.save_process_card_participation` |
| Consolidated shift summary | `qcmc_logic.api.process_card_services.get_process_card_shift_summary` |
| QA, downtime, and breakdown writes | Standard Frappe document APIs for Quality Inspection, Downtime Entry, and Asset Repair; the registered lifecycle hooks apply shared validation to form and API writes. |

The production APIs use Process Card/Job Card write checks, locked parent/Job Card rows, finite quantity and interval validation, native document saves, and correction revisions. The batch output API returns per-row results and rolls back an individual failed row to its savepoint. No new service commits the request transaction.

## Role and permission matrix

No broad role grants or permission bypasses were added. The following reflects source DocType permissions and service checks; actual site role profiles and company/user permissions still need test-site verification.

| Transaction | Source roles / service checks |
|---|---|
| Process Card | Manufacturing User: create/read/write. Manufacturing Manager and System Manager also have delete. Approval transition is restricted to Manufacturing Manager/System Manager. APIs check Process Card permission and Company/site/Workstation access. |
| Job Card and Work Order | Native ERPNext permissions remain in force. Assignment/output/participation services require readable linked Job Cards and Work Orders; mutations require Job Card write permission. |
| Participation / Employee | Job Card write plus Employee read permission; Employee must be active and, when set, belong to the Process Card Company. |
| Downtime Entry | Manufacturing User/Manager/System Manager can create/read/write; the app grants Machine Shop Foreman create/read/write and Machine Shop Supervisor read access. The summary checks read permission; linked Process Card writes validate the operator's Employee read access. |
| Quality Inspection | Native Quality Manager create/read/write/submit permissions; the app adds Plant Manager read permission at the configured permission level. |
| Asset Repair | Native Manufacturing Manager and Quality Manager permissions. Process Card context is validated without bypassing document permissions. |
| Shift Summary | Process Card, linked Job Card/Work Order, Downtime Entry, Quality Inspection, and Asset Repair read access; Employee read access is needed for participation details. List queries are permission-aware and loaded documents are checked. |

Users must also have the relevant native Desk/module access and company permissions. In particular, Quality Inspection is not made writable for Manufacturing User by this change.

## Calculation definitions

- **Machine availability:** Process Card shift duration minus the union of visible Downtime Entry intervals for the Workstation, clipped to the shift. Overlapping downtime is counted once.
- **Actual run hours:** The union of positive-output Job Card Time Log intervals, clipped to the shift, less downtime overlap.
- **Breakdown duration:** Asset Repair failure-to-completion duration is not machine downtime and is not subtracted from availability without a Downtime Entry.

Actual run hours are an output-interval proxy, not a sensor-derived machine runtime; they do not capture idle time, setup time, or unreported operation. Source event identifiers are returned in the summary.

## Earlier workbench verification and limitations

- Python syntax compilation passed for 12 focused Process Card Python source/test files.
- The custom-field fixture parsed successfully and contains 821 unique `(DocType, fieldname)` pairs, including all required Process Card transaction fields.
- `node --check qcmc_logic/public/js/process_card.js` passed. The site-free `node --test qcmc_logic/tests/test_process_card_workbench_ui.cjs` suite passed all 33 tests.
- Focused Python tests were added for operation output limits, interval unions, participation overlap/transfer boundaries, and output/participation separation. They could not be collected: system Python 3.14 lacks `orjson`, and the bench Python environment has no `pytest`. No dependencies were installed.
- Scoped `git diff --check` passed for the changed tracked source files. A repository-wide check still reports a trailing blank line in the unrelated pre-existing `qcmc_logic/qcmc_logics/report/delivery_schedule_confirmation/delivery_schedule_confirmation.py`; it was left unchanged.
- The earlier workbench verification was site-free. Final integration acceptance evidence is recorded below.
- No MCA DocType or approved rule identifying when MCA approval is required was found. The reference is free text and requiredness remains a policy decision.
- Employee participation validation checks overlapping assignments across active Process Cards.
- No authoritative Asset-to-Workstation mapping was found. Asset and Workstation are both stored on Asset Repair, but the code cannot assert that the selected Asset is the selected Workstation's physical machine.
- Downtime availability is event-based; a missing Downtime Entry leaves availability overstated. Run hours are the documented proxy above.
- QA reject reason is currently free text, not a controlled classification master. QA quantities remain separate and do not increment production-rejected quantities.
- Only submitted Manufacture Stock Entries post finished goods. Payroll calculation remains a separate workflow.


## Final integration acceptance on erp.qcstyro.local

- MFG-WO-2026-00021 completed at 10 units. QC-GUYWRF-2611-00001 requested 10 and QCQC-GUY-1 transferred 10 from RAW to WIP. Job Cards PO-JOB00020 through PO-JOB00022 and Process Cards PC-2026-00003 through PC-2026-00005 covered Thermoforming, Cutting and Packing. Downstream output was rejected before upstream confirmation and above the upstream confirmed limit.
- QC-3 received 3 units across two intervals from PC-2026-00005. It retained 1 unit from g3pffdto5i and 2 from g3qgdarp8g. Cancelling QC-2 reversed its 3 finished units and released the original allocation. QC-4 received the 3 released units.
- The scanner created drafts QC-14 and QC-15 for 2 units each after QC-5 was cancelled. Replaying the first scanner request returned QC-14. An extra unit was rejected. Drafts had zero ledger entries. The active FG ledger posted +3, +3, +2 and +2 units.
- MFG-WO-2026-00022 completed across two sets of Job Cards. PO-JOB00023 through PO-JOB00025 submitted at 6 units per operation with zero process loss. PO-JOB00026 through PO-JOB00028 submitted at 4 units per operation with zero process loss. Of two simultaneous requests for the final 4 units, one reserved QC-12 and one was rejected. The active FG ledger for QC-8, QC-9 and QC-12 totaled 10 units.
- Employee HR-EMP-00624 transferred from Thermoforming DR to Cutting PCR at the shared interval boundary. Quality Inspection MAT-QA-2026-00001 recorded an independent 08:15–09:45 QA interval. DT-00001 recorded 15 minutes downtime. Asset Repair ACC-ASR-2026-00001 submitted as Completed against a disposable test asset.
- Test BOMs used zero optional operating cost. An initial run with nonzero operating cost exposed the development Company’s missing default operating-cost account. No company accounting setting was changed.
- The development records PC-2026-00001 and PC-2026-00002 retained 3,600 and 5,000 declared units, respectively. Their linked Job Cards and Work Orders were kept as found.

## 2026-11-26 — Bridge continuation and acceptance gaps

- Corrected approval authorization in both the Process Card controller and the status-transition API to accept either Manufacturing Manager or System Manager.
- Added shift closeout validation: declared output must be confirmed and employee participation intervals closed before entering For Approval or Approved. This prevents locking incomplete operational records.
- Extended Work Order Manufacturing History with machine and shift context, employee name, QA measurement readings and units, permission-aware Material Request links from submitted Stock Entry items, and source Job Card references.
- Replaced outdated QA unit-test expectations that required QA to reference a production interval. Added tests for independent QA times, quantities, reasons and weight readings; added closeout and approval-role tests.
- WSL Node test execution: 35 passed, 0 failed, 0 skipped, including two new history-rendering tests. The new Python tests were not executed because database test execution remains disabled. No authenticated browser acceptance was performed during this continuation.
- Independently checked the DR-to-PCR participation boundary on PO-JOB00020 and PO-JOB00021. QCQC-GUY-1 has a Material Request Item reference but no Job Card header reference; existing submitted Job Card-level transfer records demonstrate the older transfer path. No Material Request with a populated Job Card field was returned by the current development API query. A fresh Job Card-level Material Request to Manufacture scenario remains required.
- MAT-QA-2026-00001 has a valid independent inspection interval but no reading rows. Live QA weight and rejection entry remain acceptance gaps. All Process Cards were Draft at the start of this continuation; approval is not yet verified in the live site.
- Changes are source-only, uncommitted; no stock, accounting, or other ERPNext records were modified. Deploy and verify on the development site before claiming acceptance.

