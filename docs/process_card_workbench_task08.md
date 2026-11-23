# Process Card Workbench Task 08 review and corrections

## Changes in this task

- Batch output context now returns `can_record_output` and `can_correct_output` for each Job Card row. This combines Process Card write permission and editable status with Job Card write permission. The individual output APIs still enforce permissions independently on every request.
- Batch correction no longer depends on the individual Process Card route's `context`; it checks the selected row's capability and gives a direct permission message. The correction API remains authoritative and records the existing audit trail.
- A batch save now reloads rows from the server. Successful rows are reconciled with the newly saved native Time Log entry, duplicate retries are labeled separately, and failed rows retain their quantities, time range, remarks, dirty state, and row-level failure message. The in-flight guard blocks repeat clicks until both save and refresh finish.
- Job Card output context separates target quantity, official ERPNext completed quantity, current Process Card output, output across all Process Cards, and remaining quantity. Remaining quantity is calculated as target minus official completed minus all operational good and rejected quantities, consistent with the write API's overproduction rule.
- SOPH lookup logic and task boundary are reviewed below. No schema or DocType changes were required.

## Storage and ERPNext compatibility

The current operational entry remains a row in native `Job Card.time_logs` with `from_time` and `to_time`; it stores QCMC metadata on the same row and keeps native `completed_qty` at zero. In ERPNext v16, `JobCard.validate_time_logs()` recalculates official completed quantity from `completed_qty`, checks cross-Job-Card time overlaps on the same workstation against Workstation production capacity, and checks employee conflicts when a row has an employee. QCMC additionally rejects overlap against any existing row on the same Job Card, including employee rows. Thus an employee Time Log occupying an interval can block machine output for that Job Card. Core workstation capacity may permit overlapping intervals across different Job Cards when capacity is greater than one. This task does not bypass core validation or modify ERPNext.

Each native Time Log row has one employee field. Multiple workers are represented as multiple rows, so associating several workers with one machine-output interval cannot be modeled as one shared row; duplicating an interval for the roster can run into native overlap checks and muddies the distinction between machine runtime and labor time. Scheduled Time also participates in workstation occupancy. Machine downtime has no dedicated record in this output flow and must not be inferred from gaps or negative computed remaining minutes.

The `Process Card` relationship is explicit in the Time Log's `qcmc_process_card` field. The Job Card can be reused on other Process Cards (for example, a later shift) subject to interval overlap, Job Card capacity, and permissions. Operational output remains separate from official completion and Work Order progressive synchronization.

## Quantity semantics

- **Target**: Job Card `for_quantity`.
- **Official completed**: Job Card `total_completed_qty`, derived from native Time Log `completed_qty`.
- **Current Process Card output**: good plus rejected output whose Time Log links to this Process Card.
- **All Process Card output**: good plus rejected output for every operational Time Log on the Job Card, across shifts and Process Cards.
- **Remaining**: max(target − official completed − all Process Card output, 0). Save validation rejects quantities that would exceed the target. Good and rejected remain separately visible and are both capacity consumption.

Current Process Card `good_qty`/`rejected_qty` totals are not substituted for official ERPNext completion. Native completed quantities remain the posting source of truth.

There is no output reconciliation link/state yet. The Workbench therefore treats every QCMC operational row as unposted. If users separately post the same physical output through official ERPNext Time Logs, the system cannot identify the duplicated physical quantity and the displayed `official completed + operational` capacity may count it twice. Do not mirror QCMC output into official quantities until a controlled reconciliation flow marks/links which entries were posted; this task does not invent a matching heuristic.

## SOPH and output item sourcing

The backend resolves SOPH from the saved Work Order Operation first: packing-named operations use `custom_pack_soph`, then fall back to operation `custom_soph`; when absent, it checks the Work Order BOM's `custom_pack_soph` for packing, otherwise `custom_soph`. No Item-level SOPH is read by this resolver. The output Item comes from Work Order Operation `custom_eps_output_item`, falling back to Job Card `production_item`. Item `custom_number_of_color` and `stock_uom` supply display metadata. The Work Order Operation is preferred because it is the order's saved operation setup. Run Hours uses `(good + rejected) / SOPH`; Remaining Minutes uses interval minutes less Run Hours × 60. Missing/zero SOPH is unavailable and negative SOPH is rejected. Both Mobile and Batch use the same server calculation, and Batch unions machine intervals by workstation for its scheduled machine-minute summary.

There is no SOPH snapshot on an output row. Historical Run Hours can therefore change if the operation/BOM rate changes. The smallest safe future alternative is a non-destructive custom field on native Job Card Time Log (for example, `qcmc_soph_snapshot`) saved with the entry, accompanied by a patch that only adds the field and does not alter existing Time Logs. Existing rows would remain explicitly unsnapshotted; reports must show the saved historical rate when present and current resolved rate only for old rows with a clear fallback indicator. Review rate source/units and migration behavior before implementing.

## Remaining native Time Log limitation and alternative

Task 01 official production rows and the Workbench's zero-quantity operational rows share one native child table. Existing employee time rows may overlap or otherwise conflict with output intervals under ERPNext validation. This also makes Time Logs an awkward long-term home if planned manpower is added later. Official output is posted only through the native `completed_qty` flow and its existing progressive Work Order synchronization; QCMC operational rows do not change those totals or post a Manufacture Stock Entry. Corrections preserve the row and append revision/actor/reason audit data.

The smallest safe decoupling alternative is a dedicated operational output child DocType owned by Process Card or a Process Card Production Entry DocType, while retaining a Job Card Link, interval, good/rejected, audit fields, and the current locked/idempotent API behavior. A later migration should copy or reconcile only QCMC operational rows, leave native employee/official Time Logs untouched, preserve original row identifiers for audit, and be separately reviewed. No such schema change is made here.

## Test commands

Run focused API tests on a development site:

```sh
bench --site <dev-site> run-tests --module qcmc_logic.tests.test_process_card_workbench
bench --site <dev-site> run-tests --module qcmc_logic.tests.test_process_card_production_output
node --test qcmc_logic/tests/test_process_card_workbench_ui.cjs
```

No user production records are required or changed by these tests.
