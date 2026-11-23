"""Warehouse Transfer destination reservations and final storage allocations."""
from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import flt, now_datetime, nowtime
from erpnext.stock.get_item_details import get_conversion_factor

from qcmc_logic import wrr_allocation as wrr
from qcmc_logic.warehouse_capacity import lock_warehouses


def get_item(item_code):
    return frappe.get_cached_doc('Item', item_code)


def uses_allocation(doc):
    return bool(doc.get('custom_storage_allocation_enabled'))


def prepare_transfer(doc):
    # New transfers opt into the revised flow, but the checkbox stays manual.
    if doc.docstatus == 0:
        doc.custom_storage_allocation_enabled = 1
    elif doc.docstatus == 1:
        previous = doc.get_doc_before_save()
        enabled = previous.get('custom_storage_allocation_enabled') if previous else frappe.db.get_value(
            'Warehouse Transfer', doc.name, 'custom_storage_allocation_enabled')
        if not enabled and doc.get('custom_apply_putaway_rule'):
            frappe.throw(_('Apply Putaway Rule must be selected before transferring. Create a new or amended transfer to use automatic storage allocation.'))
        doc.custom_storage_allocation_enabled = int(bool(enabled))


def stock_quantity(row, quantity):
    item = get_item(row.item_code)
    factor = 1
    if row.uom and row.uom != item.stock_uom:
        factor = (get_conversion_factor(row.item_code, row.uom) or {}).get('conversion_factor')
        if not factor or flt(factor) <= 0:
            frappe.throw(_('Set a valid UOM conversion for item {0}.').format(row.item_code))
    return flt(quantity) * flt(factor), item


def planning_document(doc):
    receiving = doc.docstatus == 1 and getattr(doc, '_action', None) != 'submit'
    items = []
    for row in doc.get('transfer_items') or []:
        if not row.item_code:
            continue
        quantity, item = stock_quantity(row, row.received_qty if receiving else row.issued_qty)
        if quantity < 0:
            frappe.throw(_('Transfer quantities cannot be negative.'))
        items.append(frappe._dict(name=row.name, item_code=row.item_code,
                                 stock_uom=item.stock_uom, warehouse=doc.target_warehouse,
                                 qty=quantity, conversion_factor=1, is_stock_item=item.is_stock_item))
    return frappe._dict(name=doc.name, company=doc.target_company, items=items)


def plan_allocations(doc, exclude_allocation=None):
    plans = wrr.plan_allocations(planning_document(doc), exclude_allocation=exclude_allocation)
    for rows in plans.values():
        for row in rows:
            row['source_doctype'] = 'Warehouse Transfer'
    return plans


def linked_allocations(name):
    return [frappe.get_doc('Storage Allocation', name) for name in frappe.get_all(
        'Storage Allocation', filters={'warehouse_transfer': name}, pluck='name', order_by='warehouse asc')]


def sync_allocations(doc, require_complete=False):
    if not uses_allocation(doc):
        return []
    existing = linked_allocations(doc.name)
    lock_warehouses([doc.target_warehouse] + [a.warehouse for a in existing])
    if any(a.docstatus != 0 for a in existing):
        frappe.throw(_('Storage Allocation is already submitted or cancelled.'))
    own = next((a.name for a in existing if a.warehouse == doc.target_warehouse), None)
    plans = plan_allocations(doc, own) if doc.get('custom_apply_putaway_rule') else {}
    shortages = [r for rows in plans.values() for r in rows if r['status'] == 'UNALLOCATED']
    if require_complete and shortages:
        details = ', '.join(f"{r['item_code']}: {r['suggested_qty']:g} {r['stock_uom']}" for r in shortages)
        frappe.throw(_('Cannot Receive Warehouse Transfer. Unallocated quantity: {0}. Add capacity or an eligible Putaway Rule, then save again.').format(details))
    by_warehouse = {a.warehouse: a for a in existing}
    result = []
    for warehouse in sorted(set(plans) | set(by_warehouse)):
        allocation = by_warehouse.get(warehouse)
        if not allocation:
            allocation = frappe.get_doc(dict(doctype='Storage Allocation', warehouse_transfer=doc.name,
                                             company=doc.target_company, warehouse=warehouse))
        rows = plans.get(warehouse, [])
        allocation.company = doc.target_company
        allocation.posting_date = doc.date_received or doc.date_transferred
        allocation.posting_time = nowtime()
        allocation.transaction_type = 'Warehouse Transfer'
        allocation.status = 'Draft' if rows else 'Cancelled'
        allocation.set('locations', rows)
        allocation.set('items', [])
        allocation.set('references', [])
        totals = defaultdict(lambda: [0, 0])
        for row in rows:
            total = totals[(row['item_code'], row['stock_uom'])]
            total[0] += row['original_qty']
            if row['status'] != 'UNALLOCATED':
                total[1] += row['suggested_qty']
        for (item, uom), (qty, allocated) in totals.items():
            allocation.append('items', dict(item_code=item, uom=uom, qty=qty, putaway_qty=allocated, remaining_qty=qty-allocated))
            allocation.append('references', dict(reference_doctype='Warehouse Transfer',reference_name=doc.name,item_code=item,uom=uom,qty=qty))
        wrr._write(allocation, 'save' if warehouse in by_warehouse else 'insert')
        result.append(allocation)
    return result


def submit_allocations(doc):
    if not uses_allocation(doc):
        return
    scanner_verified = bool(doc.flags.get('qcmc_wts_scanner_receipt'))
    for allocation in linked_allocations(doc.name):
        if allocation.status == 'Cancelled' and not allocation.locations:
            continue
        if allocation.docstatus != 0 or any(r.status == 'UNALLOCATED' for r in allocation.locations):
            frappe.throw(_('Warehouse Transfer allocation is incomplete or already submitted.'))
        if scanner_verified and any(
            row.status != 'VERIFIED' or not row.actual_location
            or abs(flt(row.actual_qty) - flt(row.suggested_qty)) > 1e-7
            for row in allocation.locations
        ):
            frappe.throw(_('Scanner receipt requires physically verified Storage Locations and exact quantities.'))
        allocation.status = 'Completed'
        allocation.posting_date = doc.date_received or allocation.posting_date
        allocation.completed_at = now_datetime()
        for row in allocation.locations:
            if not scanner_verified:
                # Preserve the original ERPNext receiving behavior when the
                # transfer is not completed from the physical scanner.
                row.actual_location, row.actual_qty = row.suggested_location, row.suggested_qty
                row.status = 'VERIFIED'
                row.user = frappe.session.user
                row.user_full_name = frappe.get_cached_value('User', frappe.session.user, 'full_name') or frappe.session.user
                row.scan_time = allocation.completed_at
        wrr._set_managed(allocation)
        wrr._write(allocation, 'submit')


def cancel_allocations(doc):
    allocations = linked_allocations(doc.name)
    lock_warehouses(a.warehouse for a in allocations)
    for allocation in allocations:
        allocation.status = 'Cancelled'
        if allocation.docstatus in (0, 1):
            wrr._set_managed(allocation)
            wrr._write(allocation, 'cancel' if allocation.docstatus == 1 else 'save')


def delete_draft_allocations(doc):
    for allocation in linked_allocations(doc.name):
        if allocation.docstatus != 0:
            frappe.throw(_('Warehouse Transfer has historical Storage Allocations and cannot be deleted.'))
        wrr._write(allocation, 'delete')


def get_allocation_grid_rows(doc):
    if doc.is_new() or doc.docstatus == 2 or not uses_allocation(doc) or not doc.get('custom_apply_putaway_rule'):
        return []
    statuses = {'VERIFIED': 'Allocated', 'UNALLOCATED': 'Unallocated'}
    return [dict(item_code=r.item_code,
                 location=r.actual_location if r.status == 'VERIFIED' else r.suggested_location,
                 stock_quantity=r.actual_qty if r.status == 'VERIFIED' else r.suggested_qty,
                 stock_uom=r.stock_uom, priority=r.priority, putaway_rule=r.putaway_rule,
                 status=statuses.get(r.status, 'Reserved'), warehouse=a.warehouse,
                 warehouse_allocation=a.name, source_row=r.source_row)
            for a in linked_allocations(doc.name) for r in a.locations]


def refresh_allocation_table(doc, method=None, persist=False):
    """Read-only native grid projection; linked allocations own all quantities."""
    doc.set('custom_storage_allocation', get_allocation_grid_rows(doc))
    if persist:
        doc.update_child_table('custom_storage_allocation')


def on_load(doc, method=None):
    refresh_allocation_table(doc)


def before_validate(doc, method=None):
    prepare_transfer(doc)


def on_update(doc, method=None):
    if doc.docstatus == 0:
        sync_allocations(doc)
        refresh_allocation_table(doc, persist=True)


def before_submit(doc, method=None):
    sync_allocations(doc)
    refresh_allocation_table(doc)


def before_update_after_submit(doc, method=None):
    from qcmc_logic.customs.warehouse_transfer_events import validate_update_after_submit
    validate_update_after_submit(doc, method)
    prepare_transfer(doc)
    if doc.flags.get('qcmc_wts_scanner_receipt'):
        # Existing scanner-verified Storage Allocation child rows are already
        # authoritative. Regenerating suggestions here would erase scans.
        from qcmc_logic.api.wts_picker_scanner import validate_scanner_allocations
        validate_scanner_allocations(doc)
    else:
        sync_allocations(doc, require_complete=doc.transfer_status == 'Received')
    refresh_allocation_table(doc)


def before_cancel(doc, method=None):
    lock_warehouses([doc.source_warehouse, doc.target_warehouse])
