# Stock Entry Job Card Fetch Plan

This document describes the planned `qcmc_logic` customization for fetching
Job Card details into a draft Stock Entry.

The goal is to support users who start from `Stock Entry` instead of starting
from `Job Card`, while still preserving ERPNext's Job Card tracking behavior.
ERPNext core must remain untouched.

## Business Goal

When creating a Stock Entry for manufacturing, users should be able to select
one Job Card and pull the correct materials into the Stock Entry.

Supported Stock Entry purposes:

- `Material Transfer for Manufacture`
- `Material Consumption for Manufacture`

The customization should ensure that submitted Stock Entries update Job Card
material tracking correctly by filling:

- `Stock Entry.job_card`
- `Stock Entry.work_order`
- `Stock Entry.bom_no`
- `Stock Entry.fg_completed_qty`
- `Stock Entry Detail.job_card_item`

## One Job Card Per Transaction

Each Stock Entry should be linked to only one Job Card.

Reason:

- ERPNext core has one `job_card` field on `Stock Entry`.
- `Job Card.transferred_qty` is calculated from Stock Entries where
  `Stock Entry.job_card == Job Card.name`.
- `Job Card Item.transferred_qty` and `consumed_qty` are calculated from
  `Stock Entry Detail.job_card_item`.

Allowing multiple Job Cards in one Stock Entry would break this design and make
the roll-up ambiguous. The dialog must therefore allow selecting exactly one
Job Card.

## User Flow

1. User opens a new or draft Stock Entry.
2. User selects one of the supported purposes:
   - `Material Transfer for Manufacture`
   - `Material Consumption for Manufacture`
3. User clicks `Get Items from Job Card`.
4. A dialog opens with a Job Card selector.
5. The selector/list should show enough information for the user to identify
   the correct Job Card:
   - Job Card number
   - Work Order number
   - Production item / item being produced
   - Job Card quantity
   - Already transferred or consumed quantity
   - Remaining quantity
   - Status
6. User selects one Job Card.
7. If the Stock Entry already has item rows, the system asks for confirmation
   before clearing them.
8. The system fills Stock Entry header fields from the selected Job Card.
9. The system fetches item rows and links them to Job Card Item rows.

## Displayed Job Card Data

The dialog should show one row per Job Card.

Suggested columns:

- `name`: Job Card number
- `work_order`: Work Order number
- `production_item`: item being produced
- `for_quantity`: Job Card quantity
- `transferred_qty`: transferred quantity, for `Material Transfer for Manufacture`
- `consumed_qty`: consumed quantity, if qcmc adds explicit consumption roll-up
- `remaining_qty`: calculated pending quantity
- `status`: Job Card status

For `Material Transfer for Manufacture`:

```text
remaining_qty = max(for_quantity - transferred_qty, 0)
```

For `Material Consumption for Manufacture`, the remaining quantity needs extra
care because ERPNext core consumption roll-up is tied to the `Manufacture`
purpose. The first implementation can show the Job Card-level `for_quantity`
and a server-calculated material pending flag or summary. If QCMC wants
`Material Consumption for Manufacture` to update `Job Card Item.consumed_qty`,
that should be implemented as a separate app-level hook.

## ERPNext Core Behavior To Reuse

ERPNext fills Job Card links when Stock Entry is created from Job Card through:

```text
erpnext.manufacturing.doctype.job_card.job_card.make_stock_entry
```

Important core mapping:

```python
"Job Card": {
    "doctype": "Stock Entry",
    "field_map": {"name": "job_card", "for_quantity": "fg_completed_qty"},
}
```

Important child-row mapping:

```python
"Job Card Item": {
    "doctype": "Stock Entry Detail",
    "field_map": {
        "source_warehouse": "s_warehouse",
        "required_qty": "qty",
        "name": "job_card_item",
    },
}
```

The `qcmc_logic` customization should replicate the result of this mapping from
the Stock Entry screen, not by editing ERPNext core.

Existing core functions and methods to use:

- `Stock Entry.set_job_card_data()`
  - Fills `work_order`, `fg_completed_qty`, `from_bom`, and `bom_no` when
    `job_card` is present.
- `Stock Entry.get_items()`
  - Existing server method used by the Stock Entry form to populate item rows.
- `Stock Entry.get_pro_order_required_items()`
  - Already detects `work_order.transfer_material_against == "Job Card"` and
    `self.job_card`.
  - Filters required items to the selected Job Card.
  - Adds `job_card_item` to item rows.
- `JobCard.set_transferred_qty()`
  - Recalculates Job Card transferred quantity from submitted Stock Entries.
- `JobCard.set_transferred_qty_in_job_card_item(stock_entry)`
  - Recalculates Job Card Item transferred quantity from submitted Stock Entry
    rows.
- `JobCard.set_consumed_qty_in_job_card_item(stock_entry)`
  - Recalculates Job Card Item consumed quantity for `Manufacture` entries in
    ERPNext core. QCMC may need a custom doc event if the same roll-up is
    required for `Material Consumption for Manufacture`.
- `StockEntry.update_work_order()`
  - On submit/cancel, calls Job Card update methods when `self.job_card` is
    set.

## qcmc_logic Files To Add

Add a Stock Entry client script:

```text
qcmc_logic/qcmc_logic/public/js/stock_entry.js
```

Register it in:

```text
qcmc_logic/qcmc_logic/hooks.py
```

Add to `doctype_js`:

```python
"Stock Entry": "public/js/stock_entry.js",
```

Add a server helper:

```text
qcmc_logic/qcmc_logic/api/stock_entry.py
```

Suggested whitelisted methods:

```python
@frappe.whitelist()
def get_job_cards_for_stock_entry(purpose, work_order=None, txt=None, start=0, page_len=20):
    """Return selectable Job Cards with Work Order, item, and remaining qty."""


@frappe.whitelist()
def get_job_card_details_for_stock_entry(job_card, purpose):
    """Return header values needed to fill Stock Entry from one Job Card."""
```

## Client Script Responsibilities

The custom Stock Entry JS should:

1. Add `Get Items from Job Card` on refresh.
2. Show the button only when:
   - document is draft
   - purpose is supported
3. Open a dialog for selecting exactly one Job Card.
4. Use server-side query data so the dialog can show:
   - Job Card number
   - Work Order number
   - production item
   - remaining quantity
5. Confirm before replacing existing item rows.
6. Set header fields returned by the server helper:
   - `job_card`
   - `work_order`
   - `bom_no`
   - `from_bom`
   - `fg_completed_qty`
   - `from_warehouse`
   - `to_warehouse`
7. Call the existing Stock Entry item fetch flow:

```javascript
frm.events.get_items(frm);
```

or, if needed, call the controller method directly:

```javascript
frm.call({
    doc: frm.doc,
    method: "get_items",
});
```

## Server Helper Responsibilities

The server helper should:

1. Validate `purpose`.
2. Validate that the selected Job Card exists and is not cancelled.
3. Validate that the Job Card has a Work Order.
4. Validate that the Work Order is submitted and not stopped.
5. Prefer Job Cards whose Work Order has:

```text
transfer_material_against = "Job Card"
```

6. Return enough fields to fill the Stock Entry header:

```python
{
    "job_card": job_card.name,
    "work_order": job_card.work_order,
    "bom_no": job_card.semi_fg_bom or job_card.bom_no,
    "from_bom": 1,
    "fg_completed_qty": pending_qty,
    "from_warehouse": source_or_wip_warehouse,
    "to_warehouse": wip_or_target_warehouse,
    "production_item": job_card.production_item,
    "remaining_qty": pending_qty,
}
```

Warehouse behavior:

- For `Material Transfer for Manufacture`:
  - source warehouse comes from Job Card Item rows or Stock Entry row fetch
  - target warehouse should be Work Order / Job Card WIP warehouse
- For `Material Consumption for Manufacture`:
  - source warehouse should usually be WIP warehouse
  - target warehouse is normally blank

## Important Validation

The customization must not allow mixing an existing Work Order with an unrelated
Job Card.

If the Stock Entry already has `work_order`, selected Job Card must have the
same Work Order.

If the Stock Entry already has `job_card`, selecting another Job Card should
require confirmation and should clear existing item rows.

If item rows already exist, the user must confirm before rows are cleared.

If no pending material is found for the selected Job Card, show a clear message
and do not silently create an empty Stock Entry.

## Expected Submit Behavior

After this customization fills `job_card` and `job_card_item`, ERPNext core
submit behavior should work normally.

For `Material Transfer for Manufacture`:

- `StockEntry.update_work_order()` sees `self.job_card`.
- `JobCard.set_transferred_qty(update_status=True)` runs.
- `JobCard.set_transferred_qty_in_job_card_item(self)` runs.

For manufacturing consumption/production entries:

- `StockEntry.update_work_order()` sees `self.job_card`.
- `JobCard.set_consumed_qty_in_job_card_item(self)` runs in ERPNext core for
  `Manufacture` purpose.
- If QCMC needs `Material Consumption for Manufacture` to update Job Card
  consumed quantities, add a `qcmc_logic` Stock Entry submit/cancel hook that
  calls or mirrors `JobCard.set_consumed_qty_in_job_card_item(self)` for that
  purpose.
- Work Order operation and produced quantities continue to follow ERPNext core
  lifecycle rules.

## Testing Checklist

Manual tests:

- New Stock Entry, purpose `Material Transfer for Manufacture`, no Work Order:
  select one Job Card, fields and rows populate correctly.
- New Stock Entry, purpose `Material Transfer for Manufacture`, with Work Order:
  dialog only allows Job Cards from that Work Order.
- Existing item rows: button asks confirmation before clearing.
- Submitted transfer updates:
  - `Job Card.transferred_qty`
  - `Job Card Item.transferred_qty`
- New Stock Entry, purpose `Material Consumption for Manufacture`:
  selected Job Card fills header fields and material rows correctly.
- If QCMC adds the optional consumption roll-up hook:
  `Job Card Item.consumed_qty` updates on submit and reverses/recalculates on
  cancel.
- Wrong Work Order / Job Card combination is blocked.
- Cancelled Job Cards are not selectable.

Regression checks:

- Standard ERPNext Job Card `Make Stock Entry` still works.
- Standard Work Order-based Stock Entry still works.
- Stock Entries not using the supported purposes do not show the button.

## Implementation Notes

Keep all changes inside `qcmc_logic`.

Do not edit:

```text
erpnext/erpnext/manufacturing/doctype/job_card/job_card.py
erpnext/erpnext/stock/doctype/stock_entry/stock_entry.py
erpnext/erpnext/stock/doctype/stock_entry/stock_entry.js
```

The app-level customization should behave as a guided shortcut for filling
ERPNext's existing fields, not as a replacement for ERPNext's manufacturing
logic.
