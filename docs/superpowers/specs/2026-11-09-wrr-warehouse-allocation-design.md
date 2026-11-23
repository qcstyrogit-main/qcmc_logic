# WRR bulk items and Warehouse Allocation

## Requested behavior

Inbound WRR (Purchase Receipt) has two tables. Items contains the bulk receipt quantities per item, without storage locations or location-based splitting. Warehouse Allocation appears after the first successful save and records the location splits. Apply Putaway Rule generates allocations using rule priority and available capacity, spilling remaining quantity into subsequent eligible locations as in the scanner flow.

The user confirmed that insufficient capacity must allow a draft save with the remaining quantity marked Unallocated, while submission is blocked until fully allocated.

## Approach

Use a persisted allocation child table within WRR. This is the recommended approach because the requested allocation belongs on the receipt. Keep ERPNext's native item rows, purchasing references, valuation and warehouse stock posting intact, as the scanner already separates bulk warehouse receipt from physical putaway.

A separate Warehouse Allocation document would introduce the scanner's handover, checker and picker lifecycle and extra navigation. Splitting Items by location would keep the current behavior but contradict the requested bulk table. Neither is proposed.

Implementation choices below are proposed by Codex; the user has confirmed the two tables and the insufficient-capacity behavior, not these internal details.

## Form and saved data

- Keep Items as the purchasing and quantity source. Never merge rows with different purchase-order references, rates, units, batches or other business details merely because their item code matches.
- Hide inbound source, target and rejected storage-location fields from the Items grid and row editor. Warehouse remains visible.
- Add a dedicated WRR allocation child table and a version marker for the new behavior. Do not reuse the scanner child table, which carries scanner verification fields and lifecycle assumptions.
- Show Warehouse Allocation only after the document has been saved. Rows include the source item row, item, warehouse, location, allocated stock quantity, stock UOM, priority, Putaway Rule and allocation status. An Unallocated row explicitly shows any remainder without a location.
- Generated location and quantity rows are read-only. Editing bulk items and saving regenerates the draft allocations. Keep existing submitted receipts and their stored locations unchanged.
- Enable Apply Putaway Rule for new inbound WRRs using this flow. An unchecked flag must not bypass allocation or the complete-allocation requirement at submission. Existing submitted receipts and returns retain their current behavior.

## Allocation and capacity

Use the same eligible Putaway Rules and shared occupancy/reservation sources as the scanner, restricted to the item's accepted warehouse and company. Skip disabled and ineligible locations. Respect item restrictions, unlimited-capacity rules and stock-UOM conversions.

Process eligible rules in their effective priority order. Allocate up to the location's remaining capacity, then continue with the next location. Share consumed capacity across all items and all rows in the receipt, including wildcard rules, so repeated rows cannot each consume the same free space.

Count current physical stock, other saved draft WRR reservations, scanner reservations and applicable draft stock-entry reservations exactly once. Exclude this WRR's previous draft allocation while regenerating it. Lock the relevant warehouses in a consistent order while allocating and submitting to prevent concurrent users from consuming the same capacity. The scanner currently locks its allocation document; extend the relevant scanner reservation writers to participate in the same warehouse capacity lock where needed rather than assuming that a document lock alone protects shared capacity.

Draft saving preserves every requested quantity. If rules are missing or full, record the remainder as Unallocated; never reduce the bulk item quantity to the accommodated quantity.

Recheck live capacity and regenerate the draft plan during submission under the same locks. If anything remains unallocated, reject submission with item and shortfall details. A saved draft remains available for correction. The final submitted allocations must equal the accepted stock quantities of their exact source item rows.

## Physical inventory and accounting

Warehouse stock posting continues to use native bulk receipt rows. For receipts using the new allocation version, submitted allocation rows become the physical-location source, matching the scanner's separation between warehouse stock and physical allocation. Draft allocations reserve space but do not appear as stock on hand.

Update the Storage Location Tree, movement history, Summary, per-item balance and Putaway Rule capacity calculations to include these submitted WRR allocations. Exclude the same new-version receipt from the legacy direct-location SLE contribution to prevent double counting. Preserve the existing count cutoff: only allocations after the latest physical count add to that count.

Cancellation releases location stock and reservations through document status, without editing historical allocation rows. Legacy submitted receipts keep their current SLE-location behavior. Existing returns retain their existing workflow; do not reinterpret historic return locations as inbound putaway suggestions.

For a return against a new-version receipt, populate signed return allocation rows from the referenced original item row's saved allocations, up to the still-returnable quantity at each location. Preserve exact original allocation references and allow the return's location split to be reviewed before submission. Validate that the signed total equals the returned stock quantity and that each source location has sufficient stock; block ambiguous or unavailable withdrawals rather than silently posting a return without a location. These return rows reverse physical occupancy and never run the inbound priority allocator. Historical returns remain unchanged.

## Verification

Cover priority order, full-location skipping, partial splitting, missing rules, repeated item rows, wildcard shared capacity, unit conversion, unlimited capacity, own-draft exclusion and competing reservations. Verify draft saving retains the full bulk quantity, the allocation table appears after saving, and unallocated stock blocks submission. Verify cancelled receipts contribute no stock and new receipts appear once in tree balances, history, Summary and capacity. Confirm purchasing quantities and values remain unchanged and existing submitted receipt QC-EDSA-FGWR-4 remains readable with its original history.

Run focused backend and UI tests, then a transaction-rolled-back integration check on the live site's existing rules and locations. Do not submit, cancel or rewrite the user's existing receipts for verification.

## Approved revision: existing Warehouse Allocation

The user approved reusing the existing Warehouse Allocation DocType instead of a dedicated WRR child table. Save creates or updates the linked draft allocation and reserves capacity. Receive is WRR's final status: recheck completeness and capacity, then submit WRR and its allocation in the same transaction. Cancel WRR cancels its allocation. The second WRR table displays the linked allocation rows. Scanner handover/checker/picker steps are not required for WRR allocations. Because each allocation has one required warehouse, multiwarehouse WRRs use one linked allocation per warehouse, displayed together. This approved revision supersedes the standalone WRR allocation child table proposed above.
