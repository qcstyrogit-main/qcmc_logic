# Physical Count Inventory Tag Grouping Design

## Purpose

Inventory Tag groups warehouse scan transactions for review without splitting the actual ERPNext Stock Reconciliation quantity. The resulting hierarchy is:

1. Individual immutable scan transactions.
2. Physical Count Detail groups identified by Item + Location + Inventory Tag.
3. Combined Stock Reconciliation Items identified by the existing Item + Warehouse summary key.

This design extends the existing Physical Count implementation. It must preserve additive recount behavior, transaction idempotency, per-location atomic submission, retries, ERP baseline validation, `scan_history_json`, cumulative `previous_physical_count + quantity_delta` behavior, and existing Stock Reconciliation posting behavior.

## Scope

### Included

- Add Inventory Tag to Physical Count Detail.
- Group repeated scanner transactions into one active detail row per counting identity.
- Keep every individual scan in Physical Count Scan Transaction.
- Apply Cost Acct Cnt independently to each Inventory Tag group.
- Combine all effective tag-group counts into the existing Stock Reconciliation Item quantity.
- Aggregate tag groups before comparing counts with ERP location balances.
- Update all backend consumers that currently assume one Physical Count Detail per Item + Location.
- Add migrations through tracked DocType JSON files.
- Add backend integration and regression tests.

### Excluded

- Scanner frontend changes.
- A separate Inventory Tag master or group DocType.
- Allocating ERP/book quantity among Inventory Tags.
- Splitting Stock Reconciliation Items by Inventory Tag or Storage Location.
- Backfilling tags on historical transactions.
- Removing historical Physical Count records.

## Existing Behavior

- `Physical Count Scan Transaction` stores individual scans and uses `transaction_id` as its unique identity.
- `QCMC Physical Count Result` stores submitted Item + Location snapshots.
- Repeated submissions currently append result snapshots, while helper functions select the latest row for an Item + Location identity.
- Stock Reconciliation Items currently aggregate counted locations into one Item + Warehouse row.
- Cost Acct Cnt overrides Physical Count during reconciliation review without overwriting the original Physical Count.
- ERP location stock has no Inventory Tag dimension.

## Data Model

### Physical Count Scan Transaction

Retain the optional standard Data field:

- Label: Inventory Tag
- Fieldname: `inventory_tag`
- Field Type: Data
- Required: No
- Standard filter: Yes

This remains the authoritative per-scan Inventory Tag record. No `custom_inventory_tag` field is introduced.

### QCMC Physical Count Result

Add an optional standard Data field:

- Label: Inventory Tag
- Fieldname: `inventory_tag`
- Field Type: Data
- Required: No
- Read Only: Yes
- In List View: Yes

Change only the label of the existing `variance` field to `Count Adjustment Variance`. Retain the fieldname `variance` for compatibility.

Existing rows with no tag represent the blank-tag group. No data migration or synthetic tag is required.

## Identity and Grouping

The Physical Count Detail identity becomes:

```text
Item
+ Warehouse
+ Storage Location
+ Batch
+ Serial Number
+ UOM
+ Inventory Tag
```

Inventory Tag normalization accepts `inventoryTag` and `inventory_tag`, converts the value to text, and trims surrounding whitespace only. Case and internal whitespace are preserved. A missing or whitespace-only value becomes the blank-tag group.

The existing Stock Reconciliation summary identity remains unchanged:

```text
Item + Warehouse + Batch + Serial Number + UOM
```

Inventory Tag and Storage Location do not split Stock Reconciliation Item rows.

## Submission Processing

### Transaction validation

Existing validation remains authoritative:

- `transaction_id` is required and remains the unique idempotency key.
- Inventory Tag never contributes to transaction identity.
- Quantity sign, running count, ERP baseline, warehouse, location, item, batch, serial number, and UOM validation remain unchanged.
- Duplicate transaction IDs within a request or across requests are rejected by existing rules.
- Submission replay behavior remains unchanged.

### Group construction

For each submitted Item + Location entry:

1. Normalize each individual transaction's Inventory Tag.
2. Group only the new transactions by the full Physical Count Detail identity.
3. Resolve the existing active result row for each group.
4. Calculate the group delta from that group's new transactions.
5. Update the active row's Physical Count using:

```text
new group Physical Count = previous group Physical Count + group quantity delta
```

6. Reject a group whose resulting Physical Count would be negative.
7. Append normalized transactions to that group's `scan_history_json`.
8. Increase that group's `transaction_count`.
9. Update submission/scanner metadata to the latest accepted submission while preserving individual metadata in Physical Count Scan Transaction.

Repeated scans for the same group update one active detail row. Different Inventory Tags create different detail rows. Individual Physical Count Scan Transaction rows are always inserted separately.

### Atomicity

All groups in one request remain within the existing savepoint and transaction boundary. A failure in any group rolls back:

- Every Physical Count Detail update from that request.
- Every Physical Count Scan Transaction insert from that request.
- The Stock Reconciliation summary update.
- The Physical Count Submission record.

## Physical Count and Cost Accounting

Warehouse Physical Count remains immutable audit data after scanner activity closes.

Cost Acct Cnt applies independently to each Inventory Tag group:

```text
effective group count = Cost Acct Cnt, when entered
                        otherwise Physical Count
```

The Physical Count Detail variance becomes:

```text
Count Adjustment Variance = effective group count - Physical Count
```

Examples:

| Inventory Tag | Physical Count | Cost Acct Cnt | Effective Count | Count Adjustment Variance |
| --- | ---: | ---: | ---: | ---: |
| INV-001 | 2,000 | 1,900 | 1,900 | -100 |
| INV-002 | 500 | 450 | 450 | -50 |

Cost Acct Cnt never overwrites Physical Count. Existing restrictions remain: only the latest active group row can be reviewed, only during For Recon, and negative reviewed counts are rejected.

## Combined Stock Reconciliation Quantity

The backend first aggregates effective tag groups by exact physical location:

```text
location final count = sum(effective group count for every Inventory Tag at the location)
```

The ERP location baseline is evaluated once per Item + Location identity, never once per tag. This prevents duplicate ERP baselines when a location has multiple Inventory Tags.

The existing Stock Reconciliation Item target calculation then combines location-level results with untouched warehouse stock. It continues to produce one Item + Warehouse row, subject to existing batch, serial number, and UOM dimensions.

For example:

```text
INV-001 effective count = 1,900
INV-002 effective count =   450
combined counted location = 2,350
ERP/book quantity         = 2,600
Stock Reconciliation difference = -250
```

The Stock Reconciliation Item quantity difference remains the ERP/book-stock variance. It is distinct from Count Adjustment Variance on each tag group.

## Posting

Before creating adjustment Stock Entries:

1. Select active Physical Count Detail groups.
2. Aggregate their effective counts by Item + Warehouse + Location + Batch + Serial Number + UOM, excluding Inventory Tag from the posting key.
3. Read and validate the current ERP location quantity once for that location key.
4. Compare the combined location final count with current ERP location stock.
5. Create at most one net adjustment for each location key.
6. Associate the resulting adjustment document and status with every contributing active tag group.

Posting must not overwrite per-tag Count Adjustment Variance with ERP/book variance.

## Backend Consumers

All consumers of Physical Count Detail identity must become tag-aware or explicitly aggregate tags before location-level processing:

- Latest active result selection.
- Manual-row duplicate validation.
- Cost Acct Cnt latest-row validation.
- Stock Reconciliation summary rebuilding.
- Pending adjustment posting.
- Current physical location balance queries.
- Physical location balance review queries.
- Putaway capacity calculations that consume submitted physical counts.
- Storage Location balance and movement-history queries.
- Audit/review endpoints that list current Physical Count Detail rows.

Location-level consumers must sum effective tag groups from the same latest count state rather than selecting one tag row and discarding the others.

## Historical and Backward Compatibility

- Historical Physical Count Details remain blank-tag groups.
- Historical Physical Count Scan Transactions remain valid with null/blank Inventory Tag.
- Old API callers may omit Inventory Tag.
- Existing duplicate transaction and submission replay behavior remains unchanged.
- Existing Stock Reconciliation Items remain combined and are not rewritten by migration.
- No existing Physical Count Detail is deleted or split automatically.
- Existing duplicate snapshot rows remain readable; latest-row fallback logic continues to support them.

## User Interface Effect

No custom frontend JavaScript is added in this work.

Because the child DocType field is in list view, the standard Physical Count Details grid and row dialog expose Inventory Tag after migration and metadata refresh. The variance label shown to users becomes Count Adjustment Variance.

## Error Handling

- Missing Inventory Tag is accepted as the blank group.
- A duplicate transaction ID remains a validation error regardless of tag.
- A retry with the same submission ID and identical payload returns the existing replay response.
- A reused submission ID with changed payload follows the existing payload-mismatch behavior.
- A transaction that would make its tag group negative is rejected atomically.
- ERP baseline conflicts are checked after tag groups are recombined at the location level.

## Testing Strategy

### Schema

- Both DocTypes expose optional standard `inventory_tag` Data fields.
- Neither DocType defines `custom_inventory_tag`.
- Physical Count Detail displays Inventory Tag in list view.
- The variance field label is Count Adjustment Variance.

### Grouping

- Repeated scans with the same Item + Location + Inventory Tag update one active detail row.
- Different tags at the same Item + Location create separate detail rows.
- Blank-tag scans remain supported and group together.
- Case and internal whitespace remain unchanged; surrounding whitespace is trimmed.

### Audit and idempotency

- Every individual scan creates one Physical Count Scan Transaction.
- Each transaction retains its own tag, ID, quantity, employee, device, and timestamp.
- `scan_history_json` retains each normalized transaction and tag.
- Retrying the same submission creates no duplicate transactions and does not increase group counts.
- Reusing a transaction ID across submissions is rejected.

### Cost Accounting

- Cost Acct Cnt can differ per tag group.
- Physical Count remains unchanged after review.
- Count Adjustment Variance equals Cost Acct Cnt minus Physical Count.
- Blank Cost Acct Cnt falls back to Physical Count.
- Negative Cost Acct Cnt remains rejected.

### Reconciliation and posting

- Stock Reconciliation quantity sums effective counts across all tags.
- Multiple tags at one location use the ERP baseline once.
- Multiple locations remain combined under the existing Item + Warehouse summary.
- Posting creates one net adjustment per location key, not one per tag.
- Storage Location balances equal the combined submitted tag counts plus later allocations and transfers.
- Untouched locations remain untouched.

### Regression coverage

- Additive recount behavior.
- Per-location atomic rollback.
- ERP baseline conflict behavior.
- Submission replay and duplicate protection.
- Existing untagged scanner callers.
- Existing Cost Acct Cnt rules.

## Migration and Deployment

The change is delivered through tracked DocType JSON files. Each target site runs:

```bash
bench --site <site> migrate
```

No manual Production Custom Field creation is required. After migration, clear metadata caches or restart workers only if the deployment process does not already do so.
