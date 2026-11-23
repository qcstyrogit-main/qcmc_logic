"""Capacity-aware inbound storage allocations for customer Delivery Note returns."""
from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import flt, now_datetime
from qcmc_logic import wrr_allocation as wrr
from qcmc_logic.warehouse_capacity import lock_warehouses


def uses_allocation(doc):
    return bool(doc.get('is_return') and doc.get('custom_storage_allocation_enabled'))


def prepare_return(doc):
    if doc.docstatus == 0 or getattr(doc, '_action', None) == 'submit':
        doc.custom_storage_allocation_enabled = int(bool(doc.get('is_return')))
    clear_bulk_storage_locations(doc)


def clear_bulk_storage_locations(doc):
    if not uses_allocation(doc):
        return
    # Preserve the header accounting Location, which is a different DocType.
    for table in ('items', 'packed_items'):
        for row in doc.get(table) or []:
            for field in ('location', 'to_location', 'from_location'):
                df = row.meta.get_field(field)
                if df and df.options == 'Storage Location':
                    row.set(field, '')


def planning_document(doc):
    items = []
    stock_items = set(doc.get_stock_items()) if callable(getattr(doc, 'get_stock_items', None)) else None
    for row in doc.get('items') or []:
        is_stock = row.item_code in stock_items if stock_items is not None else row.get('is_stock_item', 1)
        items.append(frappe._dict(name=row.name, item_code=row.item_code, qty=abs(flt(row.qty)),
                                 conversion_factor=row.conversion_factor, stock_uom=row.stock_uom,
                                 warehouse=row.warehouse, is_stock_item=int(bool(is_stock))))
    # Packed-item quantities are already in stock UOM. The nonstock bundle
    # parent is excluded above, so a returned bundle is never counted twice.
    parents = {row.name: row for row in doc.get('items') or []}
    for row in doc.get('packed_items') or []:
        parent = parents.get(row.get('parent_detail_docname'))
        warehouse = row.warehouse or (parent.warehouse if parent else None)
        item = frappe.get_cached_doc('Item', row.item_code)
        items.append(frappe._dict(name=row.name, item_code=row.item_code, qty=abs(flt(row.qty)),
                                 conversion_factor=1, stock_uom=item.stock_uom,
                                 warehouse=warehouse, is_stock_item=item.is_stock_item))
    return frappe._dict(name=doc.name, company=doc.company, items=items)


def plan_allocations(doc, own_allocations=None):
    plans = wrr.plan_allocations(planning_document(doc), exclude_allocation=own_allocations or {})
    for rows in plans.values():
        for row in rows:
            row['source_doctype'] = 'Delivery Note'
    return plans


def linked_allocations(name):
    return [frappe.get_doc('Storage Allocation', allocation) for allocation in frappe.get_all(
        'Storage Allocation', filters={'delivery_note': name}, pluck='name', order_by='warehouse asc')]


def sync_allocations(doc, require_complete=False):
    existing = linked_allocations(doc.name)
    if not uses_allocation(doc) and not existing:
        return []
    lock_warehouses([row.warehouse for row in (doc.get('items') or []) + (doc.get('packed_items') or [])] + [a.warehouse for a in existing])
    if any(a.docstatus != 0 for a in existing):
        frappe.throw(_('Storage Allocation is already submitted or cancelled.'))
    by_warehouse = {a.warehouse: a for a in existing}
    plans = plan_allocations(doc, {a.warehouse: a.name for a in existing}) if uses_allocation(doc) and doc.get('custom_apply_putaway_rule') else {}
    shortages = [r for rows in plans.values() for r in rows if r['status'] == 'UNALLOCATED']
    if require_complete and shortages:
        details = ', '.join(f"{r['item_code']}: {r['suggested_qty']:g} {r['stock_uom']}" for r in shortages)
        frappe.throw(_('Cannot submit Delivery Note return. Unallocated quantity: {0}. Add capacity or an eligible Putaway Rule, then save again.').format(details))
    result = []
    for warehouse in sorted(set(plans) | set(by_warehouse)):
        allocation = by_warehouse.get(warehouse)
        if not allocation:
            allocation = frappe.get_doc(dict(doctype='Storage Allocation', delivery_note=doc.name,
                                             company=doc.company, warehouse=warehouse))
        rows = plans.get(warehouse, [])
        allocation.company, allocation.posting_date, allocation.posting_time = doc.company, doc.posting_date, doc.posting_time
        allocation.transaction_type = 'Delivery Note'
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
            allocation.append('references', dict(reference_doctype='Delivery Note',reference_name=doc.name,item_code=item,uom=uom,qty=qty))
        wrr._write(allocation, 'save' if warehouse in by_warehouse else 'insert')
        result.append(allocation)
    return result


def submit_allocations(doc):
    if not uses_allocation(doc):
        return
    for allocation in linked_allocations(doc.name):
        if allocation.status == 'Cancelled' and not allocation.locations:
            continue
        if allocation.docstatus != 0 or any(r.status == 'UNALLOCATED' for r in allocation.locations):
            frappe.throw(_('Delivery Note return allocation is incomplete or already submitted.'))
        allocation.status = 'Completed'
        allocation.completed_at = now_datetime()
        for row in allocation.locations:
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
            frappe.throw(_('Delivery Note has historical Storage Allocations and cannot be deleted.'))
        wrr._write(allocation, 'delete')


def get_allocation_grid_rows(doc):
    if doc.is_new() or doc.docstatus == 2 or not uses_allocation(doc) or not doc.get('custom_apply_putaway_rule'):
        return []
    from qcmc_logic.utils import check_warehouse_access
    statuses = {'VERIFIED': 'Allocated', 'UNALLOCATED': 'Unallocated'}
    allocations = linked_allocations(doc.name)
    for allocation in allocations:
        if not check_warehouse_access(frappe.session.user, allocation.warehouse):
            frappe.throw(_('You do not have access to Warehouse {0}.').format(allocation.warehouse), frappe.PermissionError)
    return [dict(name=r.name, item_code=r.item_code,
                 location=r.actual_location if r.status == 'VERIFIED' else r.suggested_location,
                 stock_quantity=r.actual_qty if r.status == 'VERIFIED' else r.suggested_qty,
                 stock_uom=r.stock_uom, priority=r.priority, putaway_rule=r.putaway_rule,
                 status=statuses.get(r.status, 'Reserved'), warehouse=a.warehouse,
                 warehouse_allocation=a.name, source_row=r.source_row)
            for a in allocations for r in a.locations]
