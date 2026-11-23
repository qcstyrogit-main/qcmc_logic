# WRR Linked Warehouse Allocation Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task by task.

**Goal:** Keep WRR items bulk and manage priority/capacity splits in linked Warehouse Allocation documents saved and submitted with WRR.

**Architecture:** Use existing Warehouse Allocation children and a new receipt link. Generate draft allocations after WRR save; regenerate under warehouse capacity locks and require completeness before Receive. Existing allocation-based physical balances consume submitted WRR allocations; the bulk SLE has no location, preventing duplication.

**Tech Stack:** Frappe/ERPNext Python, MariaDB, form JavaScript, unittest and Node.

**Spec:** docs/superpowers/specs/2026-11-09-wrr-warehouse-allocation-design.md, revised by the user's explicit approval of existing Warehouse Allocation and Receive as the final submission point.

## Global Constraints

- Preserve existing dirty changes, legacy submitted receipts and scanner lifecycle.
- Draft shortages remain Unallocated and never reduce source item quantities; submission must fail for shortages.
- Keep purchasing references, quantities, UOM, rates and accounting in native bulk rows.
- One linked allocation per receipt/warehouse, updated without duplicates; cancel with WRR.
- Inbound locations live in the second table. Receive submits receipt/allocation atomically.

## Review Focus

- Multiple warehouses and repeated item rows must not duplicate records or reuse free capacity.
- Wildcard rules and different items share occupied capacity without adding incompatible stock units.
- Stale draft reservations and concurrent scanner/WRR saves must not overfill a location.
- Returns and cancellations must deduct physical stock exactly once and preserve legacy history.
- Direct edits/submission of WRR-managed allocation documents must not bypass WRR validation.

### Task 1: Capacity-aware planner and metadata

Files: new `qcmc_logic/wrr_allocation.py`, `qcmc_logic/warehouse_capacity.py`, `qcmc_logic/patches/setup_wrr_allocation.py`; existing WA JSON/location JSON, patches.txt; new tests/test_wrr_allocation.py.

Interfaces: `plan_allocations(doc) -> dict[warehouse, list[dict]]`, `lock_warehouses(warehouses)`, `get_reserved_quantities(warehouse, exclude_receipt=None, exclude_allocation=None, exclude_stock_entry=None)`.

- [x] Write and run failing planner tests for priority, full location, partial splits, repeated rows, wildcard shared stock, units and shortage preservation.
- [x] Add receipt link to WA and an Unallocated child status; patch creates hidden WRR version and HTML display fields plus unique receipt/warehouse index.
- [x] Implement deterministic stock-UOM planning with shared physical/reservation snapshots and warehouse locks.
- [x] Run focused planner tests.

### Task 2: Save/Receive/cancel lifecycle and read API

Files: wrr_allocation.py, overrides/purchase_receipt.py, doctype/warehouse_allocation/warehouse_allocation.py; tests/test_wrr_allocation.py.

Interfaces: `sync_allocations(doc, require_complete=False)`, `submit_allocations(doc)`, `cancel_allocations(doc)`, whitelisted `get_wrr_allocations(purchase_receipt)` checks WRR read permission and warehouse access.

- [x] Write/run failing tests for repeated save updating same record, no quantity loss, Receive shortage rejection and atomic lifecycle delegation.
- [x] Disable native item splitting for new flow; generate after successful save; replan before submission, submit after native receipt posting, cancel after native receipt cancellation. Exclude own reservations.
- [x] Guard direct mutation/submission/deletion/abandonment of WRR-managed WA. Server-generated links and source rows are authoritative.
- [x] Handle returns against new receipts with signed allocations tied to original source rows, reject unavailable physical withdrawal; legacy returns unchanged.
- [x] Run focused lifecycle and existing receipt tests.

### Task 3: Form, tree and scanner integration

Files: public/js/purchase_receipt.js, hooks.py, WA JS, storage_location.py/tree.js, warehouse_capacity.py and scanner allocation entry points; tests/test_wrr_allocation_ui.js.

- [x] Write/run failing UI checks for bulk item location hiding, delayed second table, source links and no native checkbox splitting.
- [x] Render all linked allocations as the WRR's second table with stock quantities, locations, priority, rule and Unallocated state. Repeated saves refresh display, stale unsaved items show a save reminder.
- [x] Include completed WRR allocations in popup candidate source joins/history; current per-item, summary and capacity already aggregate completed WA.
- [x] Include WRR draft reservations and physical stock in scanner occupancy; make competing reservation writers participate in common capacity locks.
- [x] Run focused UI, scanner capacity and balance tests.

### Task 4: Deployment and integration verification

- [x] Apply only the new metadata reload/patch, clear cache, and run focused regression suites.
- [x] Perform rollback-only live draft-save/re-save, shortage, Receive, return and cancellation integration checks; verify accounting bulk rows unchanged and allocation-based tree/summary reflect once.
- [x] Request independent review, address material findings with regression coverage, rerun relevant verification, and document final behavior.

## Execution ledger

Ruling: work in the existing bench app checkout, preserving all earlier changes; bench imports this checkout and the user authorized direct ERP implementation. No branch switching or commits of unrelated work.
Ruling: reuse one allocation per warehouse rather than enforcing one warehouse per WRR; the existing WA warehouse field is required and used by all occupancy queries.


Completion evidence:
- New WRR planner/lifecycle/review regression suite: 19 tests passed.
- Combined receipt, WRR, handover, scanner and summary suite: 118 tests passed. Three pre-existing scanner tests were reproduced against unchanged HEAD and excluded from that combined suite; no new scanner failures remain.
- WRR, location movement and Summary Node UI checks passed; git diff --check passed.
- Live rollback-only checks: one bulk row of 12 PCS saved as splits 3+9; repeated save retained the same WA; Receive submitted both; signed return -5 submitted; draft returns did not release inbound reservations; cancellation cancelled linked WAs; an Unallocated 12 PCS draft could not Receive and both documents remained draft. All verification data rolled back.
- Legacy tree and Summary HTTP checks preserved B4MB3L24 at 50,000 PCS used, 0 available and 100% use. ERP form metadata serves the new WRR script and fields.
- Independent review's four findings fixed with RED-to-GREEN coverage: draft-return offsets, scanner item reservations, native cancel/trash hooks and non-stock return rows.
- Database isolation is REPEATABLE-READ. Capacity writers now read underlying movements and reservations with current locking reads after the common warehouse lock, rather than trusting an earlier transaction snapshot. Read-only previews do not acquire movement locks.
- Location Transfer capacity uses the same occupancy once and takes the warehouse lock before capacity/Bin locks, preserving consistency with the changed shared reservation helper.
