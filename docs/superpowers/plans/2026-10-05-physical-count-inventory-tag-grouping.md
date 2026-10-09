# Physical Count Inventory Tag Grouping Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Group Physical Count Details by Item + Location + Inventory Tag while preserving individual scan audits and one combined Item + Warehouse Stock Reconciliation quantity.

**Architecture:** Introduce one shared grouping module that defines tag normalization, group identity, location identity, latest-row selection, and location aggregation. The scanner API will upsert one active detail row per tag group while retaining every immutable scan transaction; reconciliation review, summary, posting, and location read models will aggregate tag groups at the correct boundary.

**Tech Stack:** Python 3, Frappe/ERPNext DocTypes and document APIs, MariaDB SQL, FrappeTestCase/unittest, tracked DocType JSON migrations.

**Spec:** `docs/superpowers/specs/2026-10-05-physical-count-inventory-tag-grouping-design.md`

## Global Constraints

- Preserve additive recount behavior, transaction idempotency, per-location atomic submission, retry behavior, ERP baseline validation, `scan_history_json`, cumulative `previous_physical_count + quantity_delta` behavior, and existing Stock Reconciliation posting behavior.
- `transaction_id` remains the sole authoritative scan-transaction identity; Inventory Tag never changes it.
- Accept both `inventoryTag` and `inventory_tag`; trim surrounding whitespace only and preserve case/internal whitespace.
- Missing Inventory Tag remains valid and maps to the blank-tag group.
- Never create or consume `custom_inventory_tag`.
- Do not modify scanner frontend code.
- Do not allocate ERP/book quantity among Inventory Tags.
- Stock Reconciliation Items remain combined by the existing Item + Warehouse + Batch + Serial Number + UOM key.
- Use tracked DocType JSON and `bench --site <site> migrate`; do not create Production fields manually.
- Preserve unrelated dirty-worktree changes and do not rewrite working Physical Count code.

## Review Focus

- Mixed tagged and untagged scans at one location must produce separate active groups but one combined location count; covered in Task 2.
- Concurrent submissions targeting the same tag group must serialize under the existing reconciliation lock and must not lose either delta; covered in Task 2.
- A replay or reused transaction ID with a changed Inventory Tag must not duplicate or move quantity between groups; covered in Task 2.
- A deduction that would make one tag group negative must fail even when the combined location count stays positive; covered in Task 2.
- Same tag text across different batch/serial identities must remain separate groups and post separate location-dimension adjustments; covered in Tasks 2 and 4.

---

### Task 1: Add Physical Count Detail schema and shared grouping identities

**Files:**
- Create: `qcmc_logic/physical_count_grouping.py`
- Modify: `qcmc_logic/qcmc_logics/doctype/qcmc_physical_count_result/qcmc_physical_count_result.json`
- Modify: `qcmc_logic/api/stock_reconciliation.py`
- Modify: `qcmc_logic/overrides/stock_reconciliation.py`
- Test: `qcmc_logic/tests/test_stock_reconciliation_increment.py`

**Interfaces:**
- Produces: `normalize_inventory_tag(value) -> str`
- Produces: `physical_count_group_key(row) -> tuple[str, str, str, str, str, str, str]`
- Produces: `physical_count_location_key(row) -> tuple[str, str, str, str, str, str]`
- Produces: `latest_physical_count_groups(rows) -> dict[tuple, row]`
- Consumes: existing Frappe row objects or dict-like scanner transaction objects.

- [ ] **Step 1: Write failing schema and identity tests**

Add tests named:

- `test_physical_count_result_has_inventory_tag_group_field`
- `test_inventory_tag_normalization_trims_only_surrounding_whitespace`
- `test_group_key_separates_tags_but_location_key_does_not`
- `test_latest_group_selection_keeps_each_inventory_tag`

Assert that `QCMC Physical Count Result.inventory_tag` is optional, read-only, Data, and in list view; `variance` is labeled `Count Adjustment Variance`; normalization maps `"  Inv  001  "` to `"Inv  001"`; blank/None map to `""`; and rows differing only by tag have distinct group keys but the same location key.

Add `run_inventory_tag_grouping_tests()` beside the existing focused runners and include every grouping test added by Tasks 1-4 as those tasks progress.

- [ ] **Step 2: Run tests to verify RED**

Run:

```bash
bench --site erp.qcstyro.local execute qcmc_logic.tests.test_stock_reconciliation_increment.run_inventory_tag_grouping_tests
```

Expected: FAIL because the result DocType field and shared grouping functions do not exist.

- [ ] **Step 3: Add the tracked child-DocType field and label change**

In `qcmc_physical_count_result.json`, add optional read-only list-view Data field `inventory_tag` after `submission_id`. Change only the label of `variance` to `Count Adjustment Variance`; retain fieldname and type.

- [ ] **Step 4: Implement the shared identity functions**

In `qcmc_logic/physical_count_grouping.py`, implement the four interfaces above. Inventory identity includes Item, Warehouse, Location, Batch, Serial Number, UOM, then Inventory Tag. Latest-row ranking remains submitted/count timestamp, idx, then list position.

- [ ] **Step 5: Replace local tag/key implementations with shared interfaces**

Import the shared normalizer in `api/stock_reconciliation.py`. In `overrides/stock_reconciliation.py`, retain `physical_count_summary_key`, replace the existing location-key/latest-row implementation with imports from the grouping module, and update direct callers to use group identity where duplicate/latest behavior is tag-specific.

- [ ] **Step 6: Migrate and verify GREEN**

Run:

```bash
bench --site erp.qcstyro.local migrate
bench --site erp.qcstyro.local execute qcmc_logic.tests.test_stock_reconciliation_increment.run_inventory_tag_grouping_tests
```

Expected: migration exits 0 and Task 1 tests pass.

- [ ] **Step 7: Commit Task 1**

```bash
git add qcmc_logic/physical_count_grouping.py qcmc_logic/qcmc_logics/doctype/qcmc_physical_count_result/qcmc_physical_count_result.json qcmc_logic/api/stock_reconciliation.py qcmc_logic/overrides/stock_reconciliation.py qcmc_logic/tests/test_stock_reconciliation_increment.py
git commit -m "feat: add physical count inventory tag groups"
```

### Task 2: Upsert tag-group details while preserving scan transactions

**Files:**
- Modify: `qcmc_logic/api/stock_reconciliation.py`
- Test: `qcmc_logic/tests/test_stock_reconciliation_increment.py`

**Interfaces:**
- Consumes: Task 1 `normalize_inventory_tag`, `physical_count_group_key`, and `latest_physical_count_groups`.
- Produces: `_group_entry_transactions(entry) -> list[frappe._dict]`, each result containing `inventory_tag`, `transactions`, and `quantity_delta`.
- Produces: one active `QCMC Physical Count Result` per full group identity.
- Preserves: one `Physical Count Scan Transaction` per scanner `transaction_id`.

- [ ] **Step 1: Write failing grouped-submission tests**

Add tests named:

- `test_same_inventory_tag_scans_update_one_active_detail_group`
- `test_different_inventory_tags_create_separate_detail_groups`
- `test_mixed_tagged_and_blank_transactions_share_location_total_only`
- `test_scan_transactions_remain_individual_under_group`
- `test_group_scan_history_accumulates_across_submissions`
- `test_replay_does_not_duplicate_group_quantity_or_transactions`
- `test_reused_transaction_id_with_changed_tag_is_rejected`
- `test_tag_group_cannot_be_deducted_below_zero`
- `test_same_tag_different_batch_or_serial_remains_separate`
- `test_concurrent_same_group_submissions_do_not_lose_delta`

Use literal examples `INV-001: +1000, +1000` and `INV-002: +500`. Assert two detail rows with Physical Counts 2000 and 500, one Stock Reconciliation summary quantity of 2500 before book-stock carry-forward, and three immutable transaction rows.

- [ ] **Step 2: Run tests to verify RED**

Run the focused grouping runner. Expected: FAIL because adjustment submission still creates one location row instead of tag groups.

- [ ] **Step 3: Implement `_group_entry_transactions(entry) -> list[frappe._dict]`**

Group only the request's new transactions by normalized tag. Preserve their original order inside each group. If an entry has no transaction list, produce one blank-tag group using the existing entry-level quantity delta for backward compatibility.

- [ ] **Step 4: Change adjustment planning to use group deltas**

Inside `_submit_adjustment_entries`, keep the existing reconciliation lock, savepoint, transaction validation, and location ERP-baseline validation. Resolve the previous active row by full group key, then calculate `previous group Physical Count + group quantity delta`. Reject only when the resulting group count is negative.

- [ ] **Step 5: Upsert one active Physical Count Detail per group**

For an existing group, update that row in place; for a new group, append one row. Set `inventory_tag`, latest submission metadata, `expected_previous_count`, latest `quantity_delta`, cumulative `physical_count`, pending status, and merged transaction history. Keep Physical Count Scan Transaction insertion unchanged except for the already implemented per-transaction `inventory_tag` field.

- [ ] **Step 6: Merge group audit history without merging transaction identities**

Parse existing `scan_history_json` as a list, append only newly accepted normalized transactions, serialize with the existing stable JSON options, and set `transaction_count` to the resulting list length. Individual employee/device/timestamp values stay on transaction records; group scanner metadata reflects the latest submission.

- [ ] **Step 7: Run grouped-submission tests to verify GREEN**

Run the focused grouping runner. Expected: all Task 1-2 tests pass, including concurrency and rollback cases.

- [ ] **Step 8: Commit Task 2**

```bash
git add qcmc_logic/api/stock_reconciliation.py qcmc_logic/tests/test_stock_reconciliation_increment.py
git commit -m "feat: aggregate physical counts by inventory tag"
```

### Task 3: Apply Cost Accounting review per tag and rebuild combined summaries

**Files:**
- Modify: `qcmc_logic/physical_count_grouping.py`
- Modify: `qcmc_logic/overrides/stock_reconciliation.py`
- Modify: `qcmc_logic/api/stock_reconciliation.py`
- Test: `qcmc_logic/tests/test_stock_reconciliation_increment.py`

**Interfaces:**
- Produces: `aggregate_physical_count_locations(rows, effective_count) -> dict[tuple, frappe._dict]`
- Each aggregate contains `physical_count`, `effective_count`, one `erp_quantity_before`, and contributing `groups` for an Item + Warehouse + Location + Batch + Serial Number + UOM key.
- Consumes: Task 1 latest-group selection and Task 2 active grouped rows.

- [ ] **Step 1: Write failing review and summary tests**

Add tests named:

- `test_cost_accounting_count_applies_independently_per_inventory_tag`
- `test_count_adjustment_variance_is_recount_minus_physical_count`
- `test_blank_cost_accounting_count_uses_group_physical_count`
- `test_physical_count_stays_immutable_per_tag_group`
- `test_summary_sums_effective_counts_across_tags`
- `test_summary_counts_location_erp_baseline_once_for_multiple_tags`
- `test_summary_still_combines_multiple_locations_by_item_warehouse`

Use INV-001 `2000 -> 1900` and INV-002 `500 -> 450`. Assert row variances `-100` and `-50`, immutable Physical Counts 2000 and 500, combined effective count 2350, and one ERP location baseline.

- [ ] **Step 2: Run tests to verify RED**

Run the focused grouping runner. Expected: FAIL because current variance subtracts ERP baseline and summary baseline is repeated per result row.

- [ ] **Step 3: Implement `aggregate_physical_count_locations`**

Select latest active tag groups, sum Physical Count and supplied effective-count values per location key, retain exactly one ERP baseline per location, and retain contributing rows. For legacy duplicate snapshots, use the baseline from the highest-ranked active group row and require equal non-empty baselines within the location aggregate.

- [ ] **Step 4: Change Cost Acct Cnt validation semantics**

Keep existing workflow, latest-row, numeric, and non-negative validation. Calculate each detail row's `variance` as `effective_physical_count(result) - physical_count`, never against ERP baseline.

- [ ] **Step 5: Rebuild Stock Reconciliation summary from location aggregates**

In `rebuild_physical_count_summary`, sum effective location totals into the existing summary key. Sum each location's baseline once. Preserve the existing untouched-stock carry-forward calculation and one Item + Warehouse output row.

- [ ] **Step 6: Update manual Physical Count rows**

Manual For Recon rows use the blank-tag group, reject duplicates only within that group identity, retain their Physical Count, and calculate Count Adjustment Variance using the same per-group rule.

- [ ] **Step 7: Run review and summary tests to verify GREEN**

Run the focused grouping runner and `run_cost_acct_cnt_tests`. Expected: all Task 1-3 and Cost Acct Cnt tests pass.

- [ ] **Step 8: Commit Task 3**

```bash
git add qcmc_logic/physical_count_grouping.py qcmc_logic/overrides/stock_reconciliation.py qcmc_logic/api/stock_reconciliation.py qcmc_logic/tests/test_stock_reconciliation_increment.py
git commit -m "feat: review inventory tag count groups"
```

### Task 4: Aggregate tag groups for posting and location read models

**Files:**
- Modify: `qcmc_logic/api/stock_reconciliation.py`
- Modify: `qcmc_logic/overrides/putaway_rule_dimension.py`
- Modify: `qcmc_logic/qcmc_logics/doctype/storage_location/storage_location.py`
- Test: `qcmc_logic/tests/test_stock_reconciliation_increment.py`
- Test: `qcmc_logic/tests/test_storage_location_paths.py`

**Interfaces:**
- Consumes: Task 3 `aggregate_physical_count_locations`.
- Produces: one posting plan per location key, excluding Inventory Tag.
- Produces: SQL/read-model totals that sum latest active tag groups before applying later allocations/transfers.

- [ ] **Step 1: Write failing posting and read-model tests**

Add tests named:

- `test_posting_compares_combined_tag_count_to_location_stock_once`
- `test_posting_creates_one_net_adjustment_for_multiple_tags_at_location`
- `test_posting_links_adjustment_to_each_contributing_tag_group`
- `test_posting_keeps_count_adjustment_variance_on_tag_rows`
- `test_current_inventory_quantity_sums_latest_tag_groups`
- `test_physical_location_balances_sum_tags_before_later_movements`
- `test_storage_location_balance_sums_tag_groups_without_using_tag_variance`
- `test_storage_location_history_shows_group_count_and_individual_scan_audit`
- `test_putaway_capacity_uses_combined_effective_tag_count`

Assert that tag counts 1900 + 450 produce one location final count of 2350, one ERP comparison, one net posting variance, and no duplicated baseline or movement.

- [ ] **Step 2: Run tests to verify RED**

Run focused grouping and Storage Location test runners. Expected: FAIL because SQL/latest logic currently ranks one Item + Location row and Storage Location balances sum the repurposed tag variance.

- [ ] **Step 3: Rebuild `post_pending_pcount_adjustments` around location aggregates**

Plan one adjustment per location aggregate. Validate current ERP location quantity once, calculate `combined effective count - current`, create receipt/issue rows using the location key, then write adjustment document/status to every contributing tag group without replacing their Count Adjustment Variance.

- [ ] **Step 4: Update summary audit transaction linking**

Link posting metadata to the relevant summary audit records without changing individual scan transactions. Use submission/item/location and group tag where available; legacy summary rows with no tag remain supported.

- [ ] **Step 5: Update current-balance and review SQL**

In `_current_inventory_quantity` and `_get_physical_location_balances`, rank by the tag-aware group identity, then sum effective latest groups by location before applying allocations and transfers after the location count cutoff. Do not use Count Adjustment Variance as stock movement quantity.

- [ ] **Step 6: Update Storage Location and putaway consumers**

Change Storage Location balance/history and putaway-capacity SQL to aggregate effective group counts by location. Keep individual scan audit visibility sourced from Physical Count Scan Transaction. Ensure one submitted Physical Count location state replaces the prior location state rather than adding every historical group snapshot.

- [ ] **Step 7: Run posting/read-model tests to verify GREEN**

Run focused grouping, Storage Location, and putaway tests. Expected: all Task 4 tests pass.

- [ ] **Step 8: Commit Task 4**

```bash
git add qcmc_logic/api/stock_reconciliation.py qcmc_logic/overrides/putaway_rule_dimension.py qcmc_logic/qcmc_logics/doctype/storage_location/storage_location.py qcmc_logic/tests/test_stock_reconciliation_increment.py qcmc_logic/tests/test_storage_location_paths.py
git commit -m "fix: aggregate inventory tag groups for posting"
```

### Task 5: Migration, end-to-end verification, and handoff

**Files:**
- Modify only if verification exposes a requirement gap in files owned by Tasks 1-4.
- Test: `qcmc_logic/tests/test_stock_reconciliation_increment.py`
- Test: `qcmc_logic/tests/test_storage_location_paths.py`

**Interfaces:**
- Consumes: all prior task interfaces.
- Produces: migrated schema and verified three-level Physical Count flow.

- [ ] **Step 1: Run migration from tracked schema**

```bash
bench --site erp.qcstyro.local migrate
```

Expected: exit 0; both DocTypes contain `inventory_tag`; neither contains `custom_inventory_tag`; variance label is Count Adjustment Variance.

- [ ] **Step 2: Run focused feature suites**

```bash
bench --site erp.qcstyro.local execute qcmc_logic.tests.test_stock_reconciliation_increment.run_inventory_tag_grouping_tests
bench --site erp.qcstyro.local execute qcmc_logic.tests.test_stock_reconciliation_increment.run_inventory_tag_tests
bench --site erp.qcstyro.local execute qcmc_logic.tests.test_stock_reconciliation_increment.run_cost_acct_cnt_tests
```

Expected: all focused tests pass.

- [ ] **Step 3: Run broader regression suites**

```bash
bench --site erp.qcstyro.local execute qcmc_logic.tests.test_stock_reconciliation_increment.run_stock_reconciliation_increment_tests
bench --site erp.qcstyro.local execute qcmc_logic.tests.test_storage_location_paths.run_storage_location_path_tests
```

Expected: all tests pass. If an unrelated pre-existing failure remains, record its exact test name and unchanged before/after status rather than modifying unrelated behavior.

- [ ] **Step 4: Run static and schema checks**

```bash
./env/bin/python -m py_compile apps/qcmc_logic/qcmc_logic/physical_count_grouping.py apps/qcmc_logic/qcmc_logic/api/stock_reconciliation.py apps/qcmc_logic/qcmc_logic/overrides/stock_reconciliation.py apps/qcmc_logic/qcmc_logic/overrides/putaway_rule_dimension.py apps/qcmc_logic/qcmc_logic/qcmc_logics/doctype/storage_location/storage_location.py apps/qcmc_logic/qcmc_logic/tests/test_stock_reconciliation_increment.py apps/qcmc_logic/qcmc_logic/tests/test_storage_location_paths.py
./env/bin/python -m json.tool apps/qcmc_logic/qcmc_logic/qcmc_logics/doctype/physical_count_scan_transaction/physical_count_scan_transaction.json
./env/bin/python -m json.tool apps/qcmc_logic/qcmc_logic/qcmc_logics/doctype/qcmc_physical_count_result/qcmc_physical_count_result.json
git diff --check
```

Expected: every command exits 0.

- [ ] **Step 5: Perform a local end-to-end scenario**

Create a new local Stock Reconciliation and submit three scans at one Item + Location:

- INV-001 +1000
- INV-001 +1000
- INV-002 +500

Verify two Physical Count Detail rows (2000 and 500), three transaction records, and combined quantity 2500. During For Recon set Cost Acct Cnt to 1900 and 450; verify Count Adjustment Variances -100 and -50 and combined reconciliation quantity 2350. Submit and verify one net location adjustment and correct Storage Location balance.

- [ ] **Step 6: Review the final diff against the specification**

Confirm no frontend files changed, no `custom_inventory_tag` exists, transaction IDs are unchanged, historical blank-tag behavior remains, and no unrelated code was removed or refactored.

- [ ] **Step 7: Commit final verification-only corrections, if any**

If Step 1-6 required a scoped correction, commit only those files:

```bash
git add <scoped-files>
git commit -m "test: verify inventory tag count grouping"
```
