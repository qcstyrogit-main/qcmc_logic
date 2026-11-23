# Automatic Putaway Rule Priority

Approved behavior: new rules receive max(existing priority) + 1 within Company,
Warehouse and Item; No Item Restriction rules use a separate sequence. Existing
edits retain their position. Users manage location order without typing numbers.

- [x] Test automatic numbering, scope changes, preserving edits, disabled rules,
  ordering validation, permission checks and stale ordering protection.
- [x] Add `qcmc_logic/putaway_priority.py` for grouping, warehouse transaction
  locks and ordered-list APIs. Acquire old/new warehouse locks in sorted order
  before Frappe locks the saved rule; hold locks until transaction completion.
- [x] Integrate the existing CustomPutawayRule controller and make Priority
  read-only in the form. Keep existing data unchanged until explicitly reordered.
- [x] Add a Manage Location Order dialog with native row dragging, Move Up/Down
  buttons and Save Order. Disabled rules retain reserved positions.
- [x] Verify backend/UI tests and real save/edit/reorder behavior in an ERP
  transaction that is rolled back, then clear the site cache.

Reordering checks access to every rule, validates a complete group permutation,
and rejects stale group versions. It changes priority and modified timestamps
only. Company/warehouse/item changes append the rule to the destination group.
No changes to putaway matching, available-capacity calculations or existing
specific-item-before-unrestricted matching precedence.

Verification: 13 backend tests and the UI regression checks passed. Actual
save/edit/reorder checks assigned 1 and 2, retained priority on edit, reordered
to 2 and 1, then assigned 3; all three temporary rules were rolled back.
Two concurrent assignments using real Warehouse transaction locks produced
1 and 2 with zero Putaway Rule writes. Independent review found no important
issues. Added an idempotent warehouse/company index patch; EXPLAIN confirms
the scoped query uses that index rather than scanning the complete rule table.
