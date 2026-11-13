# Warehouse Transfer Storage Allocation Implementation Plan

Extend the approved WRR flow to Warehouse Transfer. Checkbox defaults unchecked and remains manual. Bulk transfer_items stay intact. Native read-only Storage Allocation grid appears after Save. Save reserves issued quantities initially; after submission receiving updates plan actual received quantities, including zero. Received validates complete allocation, posts existing target SLE without storage dimensions, and submits linked allocation atomically. Cancel and delete clean up managed allocations. Historical transfers stay unchanged unless opting in before Received.

- [x] Add failing planner/lifecycle tests for draft issued quantities, receiving quantities, shortages, idempotence and manual checkbox.
- [x] Reuse WRR priority/capacity planner through transfer adapter; exclude own reservation; preserve target warehouse and stock UOM.
- [x] Add transfer owner link, server-only write guard, checkbox and native grid projection metadata, custom-DocType event handlers and workflow hooks.
- [x] Keep existing source/target stock and accounting logic; bypass legacy target putaway for managed transfers and ensure unchecked new transfers respect checkbox.
- [x] Verify rollback save/resave, shortages, receiving completion and cancellation, scanner/WRR regressions; review and apply site migration.

Warehouse Transfer is a custom DocType; Frappe bypasses controller overrides for it. Use native read-only Table maintained as a server-generated projection during Save/Update and rebuilt on load. Storage Allocation remains authoritative; client grid values are always replaced.

Validation: 81 combined regression tests passed; native UI checks passed; rollback integration covered Save/re-save, real Transfer/receiving Update/Receive/Cancel, exactly-once destination physical quantity and unlocated bulk SLE. Reviewer findings addressed: new projection identities, owner-authorized submit/cancel, trusted server-managed marker, historical transfer opt-in restriction.
