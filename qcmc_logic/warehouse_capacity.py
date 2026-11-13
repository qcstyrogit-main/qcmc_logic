"""Warehouse capacity locks and reservations shared by WRR and scanner putaway."""
from collections import defaultdict

import frappe
from frappe.utils import flt


def lock_warehouses(warehouses):
    # Keep locks until the caller's transaction ends. All competing putaway
    # writers take these before locking their allocation document.
    names = sorted(set(filter(None, warehouses)))
    for warehouse in names:
        frappe.db.sql('select name from `tabWarehouse` where name=%s for update', warehouse)
    frappe.flags.capacity_locked_warehouses = set(frappe.flags.get('capacity_locked_warehouses') or ()) | set(names)


def _capacity_rows(query, warehouse, **kwargs):
    # Read-only previews and reconciliation checks should not acquire movement
    # locks. Writers first take the common warehouse lock, then use current
    # reads in the same order instead of an earlier repeatable-read snapshot.
    if warehouse not in (frappe.flags.get('capacity_locked_warehouses') or ()):
        query = query.replace('for update', '')
    return frappe.db.sql(query, warehouse, **kwargs)


def get_physical_quantities(warehouse):
    """Current physical stock, even after waiting under REPEATABLE READ.

    Frappe may read a receipt before taking the warehouse lock. Plain aggregate
    SELECTs would keep that older transaction snapshot after waiting for a
    competing save. Read the underlying movement rows with FOR UPDATE and fold
    the same count baseline/after-count movements used by location reporting.
    """
    from frappe.utils import get_datetime
    counts = _capacity_rows("""
        select pcr.*, coalesce(pcr.submitted_at, sr.modified) as counted_at
        from `tabQCMC Physical Count Result` pcr
        inner join `tabStock Reconciliation` sr on sr.name = pcr.parent
        where sr.docstatus = 1 and sr.custom_physical_count = 1 and pcr.warehouse = %s
        order by coalesce(pcr.submitted_at, sr.modified) desc, pcr.idx desc
        for update
    """, warehouse, as_dict=True)
    quantities, cutoffs, groups = defaultdict(float), {}, set()
    for row in counts:
        location = row.location or row.inventory_location
        if not location:
            continue
        group = (row.item_code, location, row.batch_no or '', row.serial_no or '', row.uom or '', row.inventory_tag or '')
        if group in groups:
            continue
        groups.add(group)
        key = (row.item_code, location)
        recount = row.cost_acct_cnt
        quantities[key] += flt(row.physical_count if recount is None or str(recount).strip() in {'', '0.000000000'} else recount)
        counted_at = get_datetime(row.counted_at)
        cutoffs[key] = max(cutoffs.get(key, counted_at), counted_at)
    allocations = _capacity_rows("""
        select wal.item_code, wal.actual_location as location, wal.actual_qty as quantity,
               coalesce(wa.completed_at, wa.modified) as moved_at
        from `tabWarehouse Allocation Location` wal
        inner join `tabStorage Allocation` wa on wa.name = wal.parent
        where wa.docstatus = 1 and wa.status = 'Completed' and wal.status = 'VERIFIED'
          and wa.warehouse = %s and coalesce(wal.actual_location, '') != ''
        for update
    """, warehouse, as_dict=True)
    receipts = _capacity_rows("""
        select item_code, location, actual_qty as quantity, posting_datetime as moved_at
        from `tabStock Ledger Entry`
        where warehouse = %s and voucher_type = 'Purchase Receipt' and is_cancelled = 0
          and coalesce(location, '') != ''
        for update
    """, warehouse, as_dict=True)
    transfers = _capacity_rows("""
        select item_code, source_location, target_location, quantity, transferred_at
        from `tabLocation Transfer` where docstatus = 1 and warehouse = %s for update
    """, warehouse, as_dict=True)

    def add(item, location, quantity, moved_at):
        if not location:
            return
        key = (item, location)
        if key not in cutoffs or get_datetime(moved_at) > cutoffs[key]:
            quantities[key] += flt(quantity)

    for row in allocations + receipts:
        add(row.item_code, row.location, row.quantity, row.moved_at)
    for row in transfers:
        add(row.item_code, row.target_location, row.quantity, row.transferred_at)
        add(row.item_code, row.source_location, -flt(row.quantity), row.transferred_at)
    units = dict(frappe.get_all('Item', filters={'name': ['in', list({key[0] for key in quantities})]},
                               fields=['name', 'stock_uom'], as_list=True)) if quantities else {}
    return {(item, location, units.get(item, '')): qty for (item, location), qty in quantities.items() if qty > 1e-9}


def get_reserved_quantities(warehouse, exclude_receipt=None, exclude_allocation=None, exclude_stock_entry=None):
    """Read current draft reservations, counting each stock-entry source once."""
    rows = _capacity_rows("""
        select wal.item_code, wal.stock_uom, wal.source_doctype, wal.source_document, wal.source_row,
            case when wal.status = 'VERIFIED' then wal.actual_location else wal.suggested_location end as location,
            case when wal.status = 'VERIFIED' then wal.actual_qty else wal.suggested_qty end as quantity,
            wa.docstatus as allocation_docstatus, wa.name as allocation, wa.purchase_receipt
        from `tabWarehouse Allocation Location` wal
        inner join `tabStorage Allocation` wa on wa.name = wal.parent
        where wa.docstatus < 2 and wa.status != 'Cancelled' and wa.warehouse = %s
        for update
    """, warehouse, as_dict=True)
    represented = {(row.source_document, row.source_row) for row in rows if row.source_doctype == 'Stock Entry'}
    result = defaultdict(float)
    for row in rows:
        if (row.allocation_docstatus != 0 or row.allocation == exclude_allocation
                or (exclude_receipt and row.purchase_receipt == exclude_receipt)):
            continue
        if row.location:
            # A pending supplier return cannot release space before submission.
            result[(row.item_code, row.location, row.stock_uom)] += max(flt(row.quantity), 0)
    drafts = _capacity_rows("""
        select sed.item_code, sed.stock_uom, sed.parent, sed.name,
            coalesce(nullif(sed.custom_actual_storage_location, ''),
                     nullif(sed.custom_recommended_storage_location, '')) as location,
            sed.transfer_qty as quantity
        from `tabStock Entry Detail` sed
        inner join `tabStock Entry` se on se.name = sed.parent
        where se.docstatus = 0 and sed.t_warehouse = %s for update
    """, warehouse, as_dict=True)
    for row in drafts:
        if row.parent == exclude_stock_entry or (row.parent, row.name) in represented:
            continue
        if row.location:
            result[(row.item_code, row.location, row.stock_uom)] += max(flt(row.quantity), 0)
    return dict(result)


def get_committed_totals(warehouse, **exclusions):
    result = defaultdict(float)
    for source in (get_physical_quantities(warehouse), get_reserved_quantities(warehouse, **exclusions)):
        for (_item, location, _uom), quantity in source.items():
            result[location] += quantity
    return dict(result)
