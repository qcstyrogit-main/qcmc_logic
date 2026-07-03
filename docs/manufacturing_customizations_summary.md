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
its latest Actual Time row. On Stock Entry submission, the FG quantity is added
to that row's Completed Qty and the Job Card total is recalculated. Cancelling
the Stock Entry reverses the same quantity from the same row. A final Job Card
must therefore have an Actual Time row before the Manufacture draft is created.

### Available Quantity

For a normal final-production Job Card:

```text
Available output =
minimum(
    Job Card transferred quantity - Work Order produced quantity,
    Work Order quantity - Work Order produced quantity
)
```

When material transfer is skipped, availability is based on the Job Card and
remaining Work Order quantities.

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

After JavaScript changes, users should perform a hard browser refresh.

## 10. Verification Completed

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

## 11. Recommended Manual Tests

1. Transfer a full-shift material quantity from an open Job Card.
2. Create a partial Manufacture entry for the first production interval.
3. Confirm raw-material rows are locked and the FG row remains editable.
4. Enter Actual Wt/Item and Wt UOM.
5. Submit and confirm Work Order produced quantity increases.
6. Create a second partial Manufacture entry from the same open Job Card.
7. Confirm available output is reduced by the first submitted output.
8. Confirm output cannot exceed transferred or remaining Work Order quantity.
9. Confirm non-Manufacture Stock Entries do not show the actual-weight fields.
10. Confirm ordinary non-Roll Work Orders remain saved and receive no Roll
    formulation updates.
