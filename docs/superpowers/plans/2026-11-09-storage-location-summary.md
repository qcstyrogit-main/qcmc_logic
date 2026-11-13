# Storage Location Summary

User request: a separate summary report following the Storage Location tree.
Confirmed content: current items and stock quantities.

Implementation uses a standard QCMC Logics Script Report and the existing
physical-location balance reader. Stock Ledger remains as reverted.

- [x] Add tests for hierarchy, branch selection, item filters, empty locations,
  warehouse isolation, distinct item counts, and mixed units.
- [x] Implement permission checks and a tree report with Warehouse (required),
  Storage Location (optional subtree), Item, and Show Empty Locations filters.
- [x] Show location ancestors, item children, and parent summaries. Count each
  item once per ancestor. Sum quantities only within the same stock UOM; mixed
  parent quantities remain blank with a quantity breakdown by UOM.
- [x] Add a Summary Report action to the Storage Location tree.
- [x] Run regression tests; register the Report with reload-doc, clear cache,
  and verify its actual web endpoint with current ERP data.

Read permissions and warehouse access are checked before reading balances.
Location and item visibility are applied before aggregation. Disabled locations
are excluded. Empty branches are hidden unless requested. The report is current
physical stock, independent of posting-date ranges, and has no additive grand
total because parent rows already include their descendants.

Verification: 8 backend tests passed; summary navigation/mixed-UOM display and
existing movement UI checks passed. Actual WSGI report request returned HTTP 200,
347 location rows and 367 item rows for FG - Sta Clara.
