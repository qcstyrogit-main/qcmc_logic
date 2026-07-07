# Manufacturing Customizations Summary

This document summarizes the manufacturing customizations implemented in
`qcmc_logic` for Roll BOM formulation and Job Card-based Stock Entries.

ERPNext core files were not modified. All behavior is implemented through
application hooks, client scripts, server helpers, and custom fields.

## 1. Roll BOM Formulation

### Scope

Roll formulation applies only when the BOM produces a Roll item.

A BOM is treated as a Roll BOM when either:

- `BOM.custom_is_roll_bom` is enabled; or
- the BOM's produced Item belongs to Item Group `Rolls`.

Ordinary BOMs are ignored by the Roll formulation customization.

### Required Quantity Calculation

For material rows that include trimming:

```text
Gross input quantity = Work Order quantity x (1 + Roll trimming percentage / 100)
Required quantity = Gross input quantity x Material ratio percentage / 100
```

For formulation materials that do not include trimming:

```text
Required quantity = Work Order quantity x Material ratio percentage / 100
```

The calculated quantity also updates the Work Order Item amount:

```text
Amount = Rate x Required quantity
```

### Material Substitution Validation

A Roll formulation category is identified by:

- Item Group
- Material Tag

The BOM defines the required total percentage for each category. A Work Order
may fulfill that category with one or more matching Items.

Example:

```text
BOM:
Virgin / PP       30%
Recoverable / PP  70%

Work Order:
Virgin Item A       30%
Recoverable Item B  40%
Recoverable Item C  30%
```

The Work Order is valid because the category totals remain:

```text
Virgin / PP       30%
Recoverable / PP  70%
```

Users may:

- replace a BOM material with another Item from the same category;
- add additional matching Items to split a category allocation; and
- remove an original BOM Item when replacement rows fully satisfy its
  category percentage.

On Work Order save, the system validates:

- every formulation Item matches its assigned Item Group and Material Tag;
- every BOM formulation category is represented; and
- the sum of Work Order `Material Ratio %` rows in each category exactly
  matches the BOM category percentage.

The draft preview permits temporary incomplete totals while users edit, such
as changing 70% to 40% before adding a second 30% row. Final validation occurs
on save.

### Draft Preview

Draft Work Orders recalculate formulation rows when:

- BOM changes
- Work Order quantity changes
- a Required Item is added or removed
- a Required Item code is changed

The preview ignores stale responses returned after a save. This prevents the
form from changing back to `Not Saved` after a successful save.

Non-Roll Work Orders receive no preview updates.

### Files

- `qcmc_logic/customs/work_order_formulation.py`
- `qcmc_logic/public/js/work_order.js`
- `qcmc_logic/hooks.py`

## 2. Job Card Selection From Stock Entry

Draft Stock Entries support selecting one Job Card from:

```text
Get Items From > Job Card
```

Supported purposes:

- Material Transfer for Manufacture
- Material Consumption for Manufacture
- Manufacture

The selection dialog displays:

- Job Card
- Work Order
- Production Item
- Job Card quantity
- Transferred quantity
- Consumed quantity
- Remaining or available quantity
- Status

Cancelled Job Cards and Job Cards linked to stopped or unsubmitted Work Orders
are not selectable.

Only one Job Card is handled per Stock Entry operation.

### Files

- `qcmc_logic/api/stock_entry.py`
- `qcmc_logic/public/js/stock_entry.js`
- `qcmc_logic/hooks.py`

## 3. Material Transfer for Manufacture

The Stock Entry screen can fetch materials directly from a selected Job Card.

The customization fills:

- Job Card
- Work Order
- BOM
- From BOM
- For Quantity
- Source warehouse
- WIP target warehouse

ERPNext's standard `Stock Entry.get_items()` method generates the material
rows and preserves `Job Card Item` references.

On submission, ERPNext updates:

- Job Card transferred quantity
- Job Card Item transferred quantities
- Work Order manufacturing transfer information

## 4. Material Consumption for Manufacture

The same Job Card selector is available for Material Consumption entries.
Materials are sourced from the Job Card or Work Order WIP warehouse.

This purpose remains separate from Manufacture:

- Material Transfer moves inventory into WIP.
- Material Consumption removes materials from WIP without receiving FG.
- Manufacture consumes materials and receives finished goods.

ERPNext's native Job Card consumed-quantity roll-up is primarily associated
with Manufacture entries. Any requirement for separate Material Consumption
entries to update Job Card Item consumed quantities should be reviewed and
tested independently before relying on that roll-up.

## 5. Incremental Manufacture During a Shift

### Business Process

A Job Card represents the entire production shift, for example 6:00 AM to
6:00 PM.

At the start of the shift:

- Materials are transferred according to the workstation's shift capacity.

During the shift:

- Production output is posted through multiple Manufacture Stock Entries,
  such as every two hours.
- The Job Card remains open until the shift is completed.

Job Card submission is not required before each Manufacture entry.

### Manufacture Flow

1. Create a draft Stock Entry.
2. Select Stock Entry Type `Manufacture`.
3. Open `Get Items From > Job Card`.
4. Select the open shift Job Card.
5. Enter the FG quantity produced for the current interval.
6. The system creates a saved draft Manufacture Stock Entry.
7. Review the FG information, then save and submit.

### Final Operation Only

For a Work Order with operations, only the Job Card for the final operation
may create a Manufacture Stock Entry:

- the final operation is the row with the highest Sequence ID;
- when multiple rows have the same Sequence ID, the last Work Order operation
  row is treated as final; and
- a Work Order with only one operation continues to use that operation.

Earlier-operation Job Cards record time and completed quantity without
creating finished-goods stock. The final operation can post incremental
finished-goods quantities only after ERPNext's standard validation confirms
that every preceding operation has completed at least the cumulative quantity
being manufactured.

For non-final operations, saving Actual Time rows immediately synchronizes
their cumulative Completed Qty to the Work Order operation, even while the
shift Job Card remains draft. This allows the next operation to proceed during
the same shift. The quantity is aggregated across all non-cancelled Job Cards
for that Work Order operation.

Only Actual Time Completed Qty contributes to downstream availability.
Job Card process loss is deliberately excluded, including after submission,
so Packing cannot exceed the physical output recorded by Injection and Drying.
Cancelling or deleting a Job Card recalculates the operation quantity.

The Job Card selector hides non-final operations for Manufacture. The same rule
is validated on the server so a direct API call cannot bypass it. Material
Transfer for Manufacture and Material Consumption for Manufacture selectors
are unaffected.

The generated Manufacture Stock Entry stores the selected final Job Card and
its latest Actual Time row for traceability. The Actual Time row remains the
source of completed output. On Stock Entry submission or cancellation, the Job
Card's Manufactured Qty is recalculated from submitted Manufacture entries
linked to that Job Card; the Actual Time Completed Qty is not changed by the
Stock Entry.

A final Job Card must therefore have an Actual Time row with Completed Qty
before the Manufacture draft is created.

### Available Quantity

For a normal final-production Job Card:

```text
Available output =
minimum(
    Job Card total completed quantity - Job Card manufactured quantity,
    Work Order quantity - Work Order produced quantity
)
```

Material transfer still controls whether enough material is available in WIP
for Stock Entry submission and backflush, but it is not the selector's finished
output quantity. The selector is based on completed production already recorded
on the Job Card.

The entered interval quantity must:

- be greater than zero; and
- not exceed the available quantity.

After a Manufacture entry is submitted, Work Order produced quantity increases
and the next available quantity decreases.

### ERPNext Operation Validation

Before generating a normal final-production Manufacture entry, the selected
Job Card operation is advanced to at least:

```text
Current Work Order produced quantity + interval Manufacture quantity
```

This allows ERPNext's standard operation-completion validation to remain
active while supporting an open shift Job Card and incremental output.

### Semi-Finished Job Cards

When a Job Card has its own `finished_good`, the customization uses ERPNext's
native Job Card Manufacture builder:

```text
JobCard.make_stock_entry_for_semi_fg_item()
```

These semi-finished Job Cards must follow ERPNext's standard submission rules.

### Draft Protection

Only one draft Manufacture Stock Entry is allowed for the relevant:

- Job Card, for semi-finished output; or
- Work Order, for normal final production.

This prevents duplicate unsubmitted output documents.

## 6. Manufacture Item Row Locking

For a Job Card or Work Order-based Manufacture Stock Entry:

- Raw-material consumption rows are read-only.
- Scrap and process-loss rows are read-only.
- Row addition, deletion, duplication, and reordering are disabled.
- The finished-good row remains editable.

The FG encoder is expected to manage only production-output information such
as:

- FG quantity
- Batch or serial information, when applicable
- Actual weight per item
- Actual weight UOM

The generated raw-material rows remain part of the document because ERPNext
requires them for stock movement, consumption, and valuation.

## 7. Backflush Behavior

Backflush means ERPNext automatically records raw-material consumption when
finished goods are posted through a Manufacture Stock Entry.

Recommended manufacturing setting:

```text
Backflush Raw Materials Based On = Material Transferred for Manufacture
```

With this setting:

- materials transferred to WIP provide the consumption basis;
- Manufacture removes the corresponding materials from WIP; and
- Manufacture receives the finished goods into the FG warehouse.

Material transfer itself is not consumption. Inventory remains in WIP until a
Manufacture or Material Consumption entry removes it.

## 8. Actual Weight Per Finished Item

Two custom fields were added to `Stock Entry Detail`:

- `custom_actual_weight_per_item`
  - Label: `Actual Wt/Item`
  - Float with six-decimal precision
- `custom_actual_weight_uom`
  - Label: `Wt UOM`
  - Link to UOM
  - Fetches from `Item.weight_uom` when configured

### Field Conditions

Both fields are visible and mandatory only when:

```text
Parent Stock Entry Type = Manufacture
AND
Stock Entry Detail is a Finished Item
```

They do not appear on raw-material rows or other Stock Entry types.

### Current Effect

Actual weight is currently traceability information only:

- It does not change Stock Entry quantity.
- It does not change stock ledger quantity.
- It does not affect valuation.
- It is not linked to Quality Inspection.
- It is not automatically copied to Batch.

The Item master should have `Weight UOM` configured if the UOM is expected to
populate automatically.

### Files

- `qcmc_logic/fixtures/custom_field.json`

## 9. Deployment

After changing fixture-defined custom fields:

```bash
bench --site <site-name> migrate
```

After changing Python hooks or server helpers:

```bash
bench restart
```

This includes changes to:

- `qcmc_logic/api/stock_entry.py`
- `qcmc_logic/customs/job_card.py`
- `qcmc_logic/customs/stock_entry.py`
- `qcmc_logic/customs/work_order_formulation.py`
- `qcmc_logic/hooks.py`

If a traceback says a Python function cannot be imported but the function
exists in the file on disk, restart the bench first. A web worker may still be
running an older loaded module.

After JavaScript changes, users should perform a hard browser refresh.

## 10. Live-Site Verification Checklist

Use this section to verify the deployed behavior on the live site.

### BOM and Roll Formulation

1. Save a Roll BOM whose formulation rows total exactly 100%.
2. Confirm the BOM marks itself as a Roll BOM.
3. Confirm a Roll BOM with no formulation rows is rejected.
4. Confirm a Roll BOM whose formulation total is not 100% is rejected.
5. Confirm a non-Roll BOM is not affected by this validation.

### Work Order Roll Materials

1. Create or edit a Work Order from a Roll BOM.
2. Confirm the Required Items grid allows formulation material rows to be
   added, removed, and edited while the Work Order is draft.
3. Use `Roll Formulation > Edit Formulation`.
4. Split one BOM category into two matching Items.
5. Apply the formulation and save the Work Order.
6. Confirm the category total must match the BOM category percentage.
7. Confirm replacement Items must have the same Item Group and Material Tag as
   the BOM category.
8. Confirm calculated Required Qty follows the Work Order quantity and Roll
   trimming percentage.
9. Confirm ordinary non-Roll Work Orders do not receive formulation updates.

### Job Card Material Transfer

1. Create a draft Stock Entry with purpose `Material Transfer for Manufacture`.
2. Open `Get Items From > Job Card`.
3. Select one Job Card.
4. Confirm the Stock Entry fills Job Card, Work Order, BOM, From BOM, source
   warehouse, WIP warehouse, and quantity.
5. Confirm material rows are fetched from the selected Job Card.
6. Submit the Stock Entry.
7. Confirm Job Card transferred quantity and Job Card Item transferred
   quantities are updated by ERPNext.

### Job Card Material Consumption

1. Create a draft Stock Entry with purpose `Material Consumption for Manufacture`.
2. Fetch one Job Card from `Get Items From > Job Card`.
3. Confirm the source warehouse is the Job Card or Work Order WIP warehouse.
4. Confirm this entry consumes from WIP and does not receive finished goods.
5. Verify whether Job Card Item consumed quantities update as expected for the
   business process. This area depends on ERPNext's native roll-up behavior and
   may need a separate customization if QCMC requires Material Consumption
   entries to update Job Card Item consumed quantities.

### Final Operation Manufacture

1. For a Work Order with one operation, create or save the Job Card and confirm
   it is treated as the final operation.
2. For a Work Order with multiple operations, confirm only the highest Sequence
   ID operation appears in the Manufacture Job Card selector.
3. If two operations share the highest Sequence ID, confirm the later Work
   Order operation row is treated as final.
4. Confirm non-final Job Cards are hidden for Manufacture but remain selectable
   for Material Transfer and Material Consumption.
5. Confirm direct server attempts to create Manufacture from a non-final Job
   Card are rejected.
6. Confirm the final Job Card must have an Actual Time row before the
   Manufacture draft can be created.
7. Create a partial Manufacture entry from the final Job Card and submit it.
8. Confirm Work Order produced quantity increases by the submitted FG quantity.
9. Confirm the selected Actual Time row on the final Job Card is not changed by
   the Manufacture entry.
10. Confirm Job Card Manufactured Qty increases by the submitted FG quantity.
11. Cancel the Manufacture entry and confirm Job Card Manufactured Qty is
    recalculated downward while Actual Time Completed Qty remains unchanged.

### Non-Final Operation Progress

1. Add Actual Time Completed Qty to a non-final Job Card and save it.
2. Confirm the matching Work Order Operation completed quantity updates while
   the Job Card is still draft.
3. Confirm the value is aggregated across all non-cancelled Job Cards for that
   Work Order operation.
4. Confirm Job Card process loss does not increase downstream availability.
5. Cancel or delete a non-final Job Card and confirm the Work Order Operation
   completed quantity recalculates.

### Incremental Output and Draft Protection

1. Transfer the shift's planned material quantity to WIP.
2. Create a partial Manufacture Stock Entry from the final Job Card.
3. Confirm the prompted quantity cannot exceed available output.
4. Confirm available output reduces after the first Manufacture entry is
   submitted.
5. Confirm a second draft Manufacture Stock Entry cannot be created for the
   same normal Work Order while another draft Manufacture entry exists.
6. For semi-finished Job Cards, confirm draft protection is per Job Card.

### Manufacture Item Rows and Actual Weight

1. Open a Job Card or Work Order-based Manufacture Stock Entry.
2. Confirm raw-material, scrap, and process-loss rows are read-only.
3. Confirm row add, delete, duplicate, and reorder controls are unavailable.
4. Confirm the finished-good row remains editable.
5. Confirm `Actual Wt/Item` and `Wt UOM` are visible and mandatory only on the
   finished-good row of a Manufacture Stock Entry.
6. Confirm non-Manufacture Stock Entries do not show or require those fields.

## 11. Troubleshooting Notes

- `ImportError: cannot import name '_get_final_operation'` on Job Card save:
  run `bench restart`. The source file has the helper, but a web worker may
  still have an older module loaded.
- No Job Cards shown in the Stock Entry selector: check the Stock Entry
  purpose, Work Order filter, Job Card cancellation status, Work Order
  submission status, Work Order stopped status, and remaining quantity.
- Final Job Card does not appear for Manufacture: confirm it is the final
  Work Order operation by Sequence ID and row order, and confirm it has
  available output.
- Manufacture draft creation says no Actual Time row exists: add at least one
  Actual Time row to the final Job Card before creating the Manufacture entry.
- Manufacture quantity is lower than expected: for normal final-production
  Job Cards, availability is limited by completed-but-not-yet-manufactured
  Job Card quantity and remaining Work Order quantity.
- Material Consumption quantities do not roll up to Job Card Item consumed
  quantity: verify ERPNext behavior for this purpose before treating it as a
  supported QCMC roll-up.
- Roll formulation preview changes after save: hard-refresh the browser to
  clear old JavaScript and retest.

## 12. Main Files Changed

- `qcmc_logic/customs/bom_formulation.py`
- `qcmc_logic/customs/work_order_formulation.py`
- `qcmc_logic/customs/job_card.py`
- `qcmc_logic/customs/stock_entry.py`
- `qcmc_logic/api/stock_entry.py`
- `qcmc_logic/public/js/work_order.js`
- `qcmc_logic/public/js/stock_entry.js`
- `qcmc_logic/hooks.py`
- `qcmc_logic/fixtures/custom_field.json`
- `qcmc_logic/patches/add_final_job_card_stock_entry_fields.py`

## 13. Verification Completed

The implementation has been checked with:

- Python compilation
- JavaScript syntax checking
- JSON validation
- `git diff --check`
- read-only live-site checks for Work Orders, Job Cards, Stock Entry Types,
  Custom Fields, and Item weight settings

The test Work Order and Job Card used while developing the incremental shift
flow were:

- Work Order: `MFG-WO-2026-00007`
- Job Card: `PO-JOB00006`

## 14. Short Smoke Test

1. Transfer a full-shift material quantity from an open Job Card.
2. Create a partial Manufacture entry for the first production interval.
3. Confirm raw-material rows are locked and the FG row remains editable.
4. Enter Actual Wt/Item and Wt UOM.
5. Submit and confirm Work Order produced quantity increases.
6. Create a second partial Manufacture entry from the same open Job Card.
7. Confirm available output is reduced by the first submitted output.
8. Confirm output cannot exceed completed-but-not-yet-manufactured Job Card
   quantity or remaining Work Order quantity.
9. Confirm non-Manufacture Stock Entries do not show the actual-weight fields.
10. Confirm ordinary non-Roll Work Orders remain saved and receive no Roll
    formulation updates.
