# Delivery Scheduling — Manual Acceptance

Use the verified development site `http://erp.qcstyro.local:8000`. Use existing customers, items, and warehouses. Do not use seeded Codex masters. No passwords or session data belong in this document. Do not submit a Delivery Note, invoice, stock transaction, or accounting entry during these checks.

## Prerequisites

- A disposable, newly created development Sales Order with SO Type REGULAR, company, non-provincial warehouse, and delivery date. Keep it clearly labeled as a manual acceptance record and preserve all original SO amounts.
- Sales Coordinator account with SO read access and transaction scope for its company and warehouse.
- Stock Confirm User account with warehouse transaction scope.
- Credit and Collection approver account for the normal SO approval flow.
- Use the existing development site. Do not modify SO `26-00037` or the 16 Unreconciled historical schedules. Open **Schedule Deliveries** on SO `26-00038`; verify its current schedules remain visible and unchanged. If the form reports unreconciled records, verify they remain visible and unchanged, then stop edits to those rows.

## Procedure

1. **Schedule a new draft SO.** As Sales Coordinator, create a draft SO with at least two existing items and dates. Select **Schedule Deliveries**. The SO is saved as a draft, then the combined schedule editor opens. Verify the items appear together and each row retains its source SO Item.

2. **Initialize defaults when no plan was entered.** On a separate eligible draft SO, leave dates on the SO Items (or the parent Delivery Date) and enter no schedule plan. Select **Schedule Deliveries**. Verify one initial row per unscheduled item, using the item date first and parent date as fallback. Original QTY equals outstanding quantity less delivered/draft-allocated quantity, Changes is zero, and Total equals Original QTY. Repeat the action; no duplicate rows should appear. Verify SO Item quantity, date, rate, taxes, discounts, and totals are unchanged.

3. **Approve the SO normally.** Submit through **Sales Coordinator → Submit for Approval**, then **Credit and Collection approver → Approve**. Verify standard ERPNext SO approval completes and schedule records remain linked to their original SO Items. Do not use a direct submit or database write.

4. **Edit Logistics commitments with autosave.** As Stock Confirm User, open **Delivery Schedule Workbench** and change a row's confirmed quantity, reason, or remarks. Leave the field; verify the value saves without a Save or Confirm button and is visible to Sales after refresh. For a transfer, enter both transfer quantity and destination date; after leaving the field, verify the move applies atomically, with source Changes negative, destination QTY blank/zero, destination Changes positive, and conserved Totals.

5. **Reconcile commitment values.** On the same workbench, verify original Sales QTY/date and promise attribution remain intact; source/destination From Schedule and From Date details identify the movement; each row Total equals Original QTY + Changes; the item sum is conserved. No SO commercial values change.

6. **Create Delivery Note details from the confirmed quantity.** As Sales Coordinator, select a Logistics-confirmed schedule and choose **Create Delivery Note Details**. In the review dialog, verify the default quantity equals Logistics Confirmed QTY. If testing a partial amount, enter a positive quantity below the confirmed amount in the same dialog; values above the confirmed amount or below an existing Draft DN allocation must be rejected. Verify any excluded balance remains on a pending source-linked schedule.

7. **Review the selected Delivery Note details.** Verify the preview lists the exact SO, customer, item, schedule date, warehouse destination, Logistics-confirmed quantity, selected DN quantity, UOM, current draft allocation, and quantity to add. If another confirmed row shares the SO/date but was not selected, verify it is listed as omitted and is not added. Cancel once; no DN should be created. Repeat and confirm creation of Draft DNs only.

8. **Verify Draft DN reconciliation.** Open each created Draft DN and verify item quantity, `against_sales_order`, original `so_detail`, schedule reference, warehouse, and schedule date/grouping. Refresh the workbench and retry: existing eligible Draft DN quantities should consolidate without duplicate DNs. No DN is submitted.

9. **Check role boundaries.** As Sales Coordinator, verify original schedule creation and Delivery Note detail creation are available only inside permitted company/warehouse scope. As Stock Confirm User, verify Logistics fields autosave in permitted warehouse scope and Sales-only Delivery Note creation is unavailable. Confirm stale concurrent edits are rejected; do not grant broad Sales Order write access to make a check pass.

10. **Refresh, retry, duplicates, and rejection.** Refresh both workbench and SO form; verify persisted schedules and totals remain stable. Retry an already completed transfer/request and verify idempotency. Open the same schedule in two sessions: after one saves, the stale save must be rejected with a refresh instruction. Verify zero quantity, missing date/remarks, over-allocation, closed/on-hold/canceled orders, and quantities beyond Logistics confirmation are rejected with field or business-specific messages.

## Additional current acceptance

- Approved Regular SO with no schedules appears by the SO Item delivery date. Merely viewing it creates no schedule. Logistics confirmation creates one baseline. A full date transfer preserves the original promise and creates a zero-original destination. Retry and concurrent attempts cannot duplicate it.
- FOB, FOB-DIRECT, LOCAL, drafts, closed, canceled, and otherwise ineligible orders remain outside the workbench.
- A selected Logistics reason is sufficient with empty free-text remarks. Good to go disables transfer fields. Quantity reasons disable date transfer. Next Delivery Date and Off Route move the full eligible quantity.
- Logistics autosave shows Saving, Saved, or failure. Tab between fields and edit two rows while requests are in flight. Verify focus and unsaved values survive. Verify stale concurrent writes fail clearly.
- Fully allocated items disable Add and Remove in the SO editor. Past rows are read-only there. Future eligible rows remain editable. Verify discard warning, per-item plus action, same-date merged remarks, and quantity limits.
- Created Draft DNs remove their source schedules from the pending queue. Full transfers remove empty source rows and show the destination under its date. Verify overdue inclusion, mixed-UOM cards, distinct draft counts, and truncation warnings.
- In Printing, verify DR preview, duplicate numbers, permissions, release to To Deliver and Bill with docstatus zero, and optional invoice behavior. QC invoice preview must explicitly use Charge Invoice Receipt QC.
- Snapshot and reload commercial SO fields, taxes, discounts and totals around all mutations, including VAT-inclusive and discounted fixtures.

## Evidence and recording

Earlier accepted evidence and current unverified gates are listed in the [checkpoint](delivery_workbench_implementation_checkpoints.md). Record SO names, schedule/movement IDs, Draft DN names, roles, pass/fail, screenshots and exact errors. Keep credentials and sessions outside the app repository.

Use the shared Playwright installation at /home/qcmc_admin/browser-automation. Keep dependencies, sessions, traces and screenshots there. Final stock/accounting posting requires separate authorization.
