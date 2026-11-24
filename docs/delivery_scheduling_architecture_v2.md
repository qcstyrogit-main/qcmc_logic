# Delivery Scheduling

Current agreed workflow, consolidated November 23, 2026. Technical module names containing v2 are retained identifiers. There is one scheduling system.

## Operational flow

Sales Order scheduling → Delivery Schedule Workbench → Create Draft Delivery Note details → Delivery Note Printing Workbench → To Deliver and Bill → warehouse submission.

The two operational workbenches are Delivery Schedule Workbench and Delivery Note Printing Workbench. The retired Sales Order Delivery Scheduling Workbench redirects to Delivery Schedule Workbench. Its page APIs are unwhitelisted. The three former delivery Query Reports remain disabled compatibility wrappers and their navigation entries are filtered from Desk boot data.

## Eligibility and original Sales schedules

The workbench accepts submitted, open Sales Orders with SO Type REGULAR. Open ERPNext statuses are To Deliver and Bill, To Deliver, and To Bill. Company, warehouse, document access, and applicable transaction scope are validated by the services.

Sales enters dates and quantities through Schedule Deliveries on the Sales Order. Multiple dates use separate SO Delivery Schedule records linked to the unchanged original SO Item. The schedule ledger contains quantities and operational decisions.

An SO Item with no schedule records appears in the workbench using its item delivery date. Viewing that row creates no schedule. Logistics' first valid save creates the original commitment and applies the decision in the same transaction. Existing draft allocations and submitted fulfillment reduce available unscheduled demand. Current implementation excludes provincial warehouses.

## Quantity and promise model

- Sales-created rows establish Original Qty and the original Sales promise date. Changes starts at zero.
- Total equals Original Qty plus net Changes and equals the current planned quantity.
- A quantity move reduces Changes on the source and creates a source-linked destination with Original Qty zero, displayed blank, positive Changes, and Total equal to the quantity moved.
- Original commitments remain immutable. Movement records retain source schedule, source date, transaction identity, reason, actor, and original promise attribution.
- Draft DN quantities reserve demand. Submitted DN quantities represent actual fulfillment.
- Scheduling operations preserve SO quantities, prices, taxes, discounts, totals, and original SO Item references.
- Original-promise OTIF uses the original Sales commitment. A revised delivery date does not replace that promise.

## Sales Order editor

The editor shows all saved schedule rows in one dialog with per-row quantities and balances. Add and Remove are disabled for fully scheduled items. Past-date rows are read-only in this editor and are moved through Logistics. Today and future rows remain subject to allocation and permission checks.

A plus button adds another date for the same item. Same-date merging preserves both remarks and displays the combined quantity. Closing with unsaved edits requests discard confirmation. Disabled rows explain the applicable restriction.

Existing rows lacking original baseline evidence require backend review. Routine scheduling opens without a reconciliation popup. A genuine data inconsistency may still block an edit. Historical rows must not be assigned invented promises.

## Logistics autosave

Logistics edits save on leaving a field. The workbench displays save status and retains unsaved values after failure. Database row locks and modified timestamps protect concurrent updates. A stale request must be rejected and refreshed.

The selected Logistics reason is sufficient. Free-text Logistics remarks are optional.

- Good to go confirms the scheduled quantity and disables transfer fields.
- Stock Availability, Customer Request, Truck Overload, and Sales Error allow quantity decisions and disable date transfers.
- Off Route and Next Delivery Date enable a destination date and use the full scheduled quantity for the transfer.
- A complete transfer is applied atomically during Logistics autosave.
- Protected Delivery Notes, delivered quantities, and current allocations restrict movements.

A stock shortage requires a user decision. It does not automatically reschedule demand.

## Daily workbench queue

Show pending schedules and eligible SO Items awaiting their first schedule. Hide schedules with an active Draft or submitted DN and emptied transfer sources. Canceled-DN history remains subject to replacement authorization.

At day end, pending quantities should have Draft DN details or be moved to another date. Include overdue exposes missed earlier dates. An empty daily queue means today's scheduling handoff is complete.

Summary cards show pending SOs, pending schedule items, remaining scheduled quantity grouped by UOM, and distinct Draft DNs for the selected date. The service currently limits query results and warns about possible truncation. Complete large-queue totals remain an acceptance concern.

## Sales creates Draft Delivery Note details

Sales selects Logistics-confirmed rows. The preview groups selected items by SO, date, and warehouse, displays confirmed quantities and existing reservations, and lets Sales choose a positive DN quantity within the Logistics cap and above existing allocations.

Creating details records Sales authorization and creates or consolidates Draft DNs atomically. Any excluded quantity remains on a pending source-linked schedule with movement provenance. Selected rows alone are included. Same-date unselected rows are displayed as omitted.

Keep original so_detail and schedule links. Compatible items consolidate within the same SO/date/warehouse context. An existing unnumbered Draft without an active invoice can absorb valid additional quantities. Progressed, numbered, submitted, and invoiced DNs are protected.

## Printing and optional invoicing

Invoicing Clerk assigns a unique DR number, previews the DR, and releases the Draft through the Frappe Submit for Delivery workflow action to To Deliver and Bill with docstatus zero. Warehouse submission is the standard ERPNext submit operation.

The DR uses the Delivery Note default print format. QC Styropackaging Corporation invoice previews explicitly use Charge Invoice Receipt QC. Other companies currently use the Sales Invoice default.

Invoice creation is optional. Native ERPNext mapping and calculation produce a draft Sales Invoice with verified DN item linkage and matching DR/invoice references. Duplicate invoice creation is checked. Printing and preview must not submit invoices or DNs.

## Lifecycle, concurrency, and integration

Draft deletion releases reservations. Submitted cancellation changes derived fulfillment and requires explicit replacement authorization where demand must be restored. Returns do not automatically reopen demand.

Short delivery and whole-DN moves use controlled services with reason, scope, current-state, protected-document, and quantity-conservation checks. Preserve DN identities and source promise attribution.

Schedule and DN updates publish after-commit invalidation notifications. Workbench refresh must preserve local edits. Shared SO locks serialize scheduling and allocation writers.

Native MPS reads native ERPNext delivery schedule data. This project has no MPS adapter. Operational MPS usage requires a separate compatibility decision.

## Source ownership

SO Delivery Schedule and Delivery Schedule Movement define schedule state and history. delivery_schedule_service owns schedule creation, balances, transfers, and draft allocations. delivery_schedule_collaboration_v2 handles the workbench handoff. delivery_schedule_revision handles DN corrections. delivery_printing_service handles printing and optional invoice actions.

sales_order_schedule_split still provides shared locking helpers. sales_order_scheduling_service still provides Sales permission checks. Their technical names alone are not grounds for removal.

## Verification

See [manual acceptance](delivery_scheduling_manual_acceptance.md) and [current checkpoint](delivery_workbench_implementation_checkpoints.md). Source implementation and isolated checks do not establish live acceptance. No production deployment or historical migration is included.
