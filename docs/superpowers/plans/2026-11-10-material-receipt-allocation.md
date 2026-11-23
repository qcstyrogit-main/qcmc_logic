# Material Receipt Storage Allocation Plan

Apply the approved WRR/WT/DN allocation flow only to exact Stock Entry Type Material Receipt, confirmed by the type's authoritative purpose. Reuse existing manual Apply Putaway Rule checkbox (default off). Preserve bulk item rows and native valuation, stock, accounting, manufacture and scanner logic. Save reserves positive stock quantities per target warehouse in managed Storage Allocation. Native virtual table derives from allocations; unallocated quantities block Submit. Submit completes allocations atomically; Cancel/Delete clean up. Other types and historical submitted entries keep existing behavior.

- [x] Failing tests for type gate, bulk quantities/UOM/capacity, manual checkbox, shortages, owner guard and preserving other types.
- [x] Add stock_entry owner Link/index, virtual native table/marker metadata and generic source support.
- [x] Material Receipt planner/lifecycle, self reservation exclusion and clear bulk storage dimensions/scanner reservation fields only for this flow.
- [x] Integrate existing CustomStockEntry superclass hooks and RPC so native checkbox does not split Material Receipt bulk rows; preserve other RPC purposes.
- [x] Native form UI and table lazy-load regression.
- [x] Real rollback Save/re-save/shortage/Submit/Cancel checks, combined regressions, fresh review and cache refresh.

Validation: 124 combined regression tests and five native UI suites pass. Real rollback Material Receipt Save/re-save, shortage blocked before SLE, Submit, Cancel, generic source links and exactly-once physical stock checks pass. All verification documents/stock movements rolled back. Fresh read-only reviewer found no important issues. Only the exact Material Receipt type enables this flow; existing other-type behavior and Manufacture validations covered by regression tests.
