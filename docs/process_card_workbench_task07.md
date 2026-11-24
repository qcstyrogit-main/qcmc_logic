# Process Card Workbench: mobile and batch encoding

## Existing integration reviewed

- The Floor Navigator stores machine-to-Workstation links in `Production Floor Layout.layout_json` and opens the Process Card Workbench from machine or building context.
- A Process Card contains the shift window and explicit links to standard ERPNext Job Cards. Job Cards and Work Orders remain the manufacturing records.
- Task 06 operational output is stored on native Job Card Time Log child rows using QCMC output fields. `completed_qty` is always zero for those rows; official Job Card and Work Order totals are not changed by this encoder. Task 01's progressive Work Order synchronization skips these operational-only updates.
- Existing output correction stores revision history, actor, reason, timestamp, and prior/new values. The historical timeline still shows old configured checkpoint intervals and any saved intervals outside that schedule.

## New entry behavior

- Mobile Encoding records any positive `from_time` / `to_time` contained in the Process Card shift. It uses the shared output service, and remembers the current reporting period and unsaved form values in browser storage.
- Batch Encoding is opened from a building in the Floor Navigator or from a Process Card's mode switch. The user supplies the site, production date, Shift Type, optional building, and default interval before loading rows. That interval is copied to each eligible linked Job Card row and can be changed row-by-row.
- Batch writes use the same `save_process_card_output` service as Mobile Encoding. Each submitted row gets a savepoint and an individual result; one row failure does not roll back successful rows. Existing matching intervals are shown and require the audited correction route instead of being overwritten.
- Workstation overlap, Process Card membership/status, shift bounds, Job Card access, duplicate identity, and quantity precision are validated server-side. Official ERPNext completed quantities and Stock Entries are untouched.

## SOPH and time calculation

- Machine SOPH comes from the Work Order's BOM `custom_soph`, calculated from cavity count × rate per minute × 60. When a Work Order Operation has `custom_eps_output_item`, that operation output Item is used for the displayed code, description, stock UOM, and color count.
- Packing operations use `Work Order Operation.custom_pack_soph` when populated, with BOM `custom_pack_soph` as fallback; general SOPH falls back to BOM `custom_soph`.
- Color count uses the existing output Item `custom_number_of_color` field. No color field was added. Quantities are entered in the output Item's stock UOM; no alternate-UOM conversion rule exists in the inspected production configuration.
- Run Hours = (Good Output + Rejected Output) / SOPH. Computed Remaining Minutes = reporting interval minutes − Run Hours × 60. A missing/zero SOPH is reported unavailable; a negative result is visibly flagged. These calculations do not classify downtime.
- The existing output row schema has no SOPH snapshot field. Current calculations use the saved Work Order operation/BOM values, so a later SOPH change can change displayed historical calculations. A rate snapshot requires a separately reviewed, non-destructive schema migration.

## Compatibility and limits

- Existing Time Log rows are not migrated or rewritten. Two-hour schedules remain a historical timeline view, not a new-entry constraint.
- Native Job Card Time Logs share a single time range across all employees. Existing employee logs therefore continue to block overlapping output periods. This implementation does not change ERPNext's native overlap validation or add a separate output DocType.
- Batch context is permission-filtered and capped at 250 Process Cards / 500 output rows per load. Narrow the date, shift, or building if a site exceeds those limits.
- Routine output entry and correction are supported in both modes. Batch mode shows the union of scheduled time ranges per workstation so shared rows do not double-count scheduled machine minutes. This is not actual run time or classified downtime; per-operation Run Hours remain separate. A full production report/export and downtime classification are future work.
- The mobile form is responsive and browser-storage based; it is not an offline/PWA application.

## Dev validation

No schema migration is needed for this task. No production data or production deployment was touched. Run relevant tests on a development site:

```sh
bench --site <dev-site> run-tests --module qcmc_logic.tests.test_process_card_production_output
bench --site <dev-site> run-tests --module qcmc_logic.tests.test_process_card_workbench
node qcmc_logic/tests/test_process_card_workbench_ui.cjs
node qcmc_logic/tests/test_production_floor_workbench_ui.cjs
```

The standard SOPH source and saved floor layouts remain in their existing DocTypes. Task 08 can add approved downtime/shared-machine reporting and a snapshot migration after production accounting rules are agreed.
