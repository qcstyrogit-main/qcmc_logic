# Delivery Note Return Storage Allocation Plan

Apply the existing approved WRR/WT flow to inbound customer returns only. Manual checkbox defaults off, shown only for is_return. Keep commercial item rows bulk. Save synchronizes linked draft Storage Allocations per target warehouse using current shared capacity and priority; positive stock quantities derive from negative return qty times UOM conversion. Native virtual read-only ERP table derives from linked allocations. Shortages remain Unallocated in draft and block Submit. Submit and Cancel run native Delivery Note stock/accounting behavior and allocation lifecycle atomically. Outbound notes and historical submissions retain existing behavior.

- [x] Regression tests for return sign/UOM, multiwarehouse self-exclusion, shared capacity, manual checkbox, outbound behavior, shortages, owner guard.
- [x] Add Delivery Note owner Link, metadata checkbox/marker/virtual native grid and unique owner+warehouse key.
- [x] Add allocation adapter and lifecycle using existing shared WRR planner; preserve native controller behavior.
- [x] UI return-only checkbox/grid, clear storage inventory dimensions on inbound bulk rows only.
- [x] Verify rollback draft/save/submit/cancel, stock exactly once, native/outbound regressions; request review and apply metadata/cache updates.

Validation: 92 focused regression tests pass; four native UI suites pass. Rollback integration copied MAT-DN-2026-00230, saved/re-saved, blocked unallocated final submission, added temporary location/rule, submitted through the real workflow, verified one positive SLE without storage dimension and one physical +2 allocation, then cancelled and verified reversal. All temporary records rolled back. Fresh review has no remaining important findings. The broader warning suite has one pre-existing wording assertion failure, independently reproduced with unchanged HEAD warning implementation/tests.
