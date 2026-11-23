"""WRR bulk items and their linked, capacity-aware Storage Allocations."""
from collections import defaultdict
from contextlib import contextmanager
import uuid

import frappe
from frappe import _
from frappe.utils import flt, now_datetime

from qcmc_logic.overrides.putaway_rule_dimension import get_ordered_dimension_putaway_rules
from qcmc_logic.warehouse_capacity import get_physical_quantities, get_reserved_quantities, lock_warehouses

EPSILON = 1e-9


def get_location(name):
    return frappe.get_cached_doc('Storage Location', name)


def uses_allocation(doc):
    return bool(doc.get('custom_wrr_allocation_enabled'))


def _stock_quantity(item):
    # Stock quantity is recomputed from the authoritative bulk quantity, not a
    # client-supplied stock_qty that may be stale after editing qty or UOM.
    return flt(item.qty) * (flt(item.conversion_factor) or 1)


def _allocation_row(doc, item, quantity, rule=None):
    return dict(
        allocation_id=str(uuid.uuid4()), source_doctype='Purchase Receipt',
        source_document=doc.name, source_row=item.name, item_code=item.item_code,
        stock_uom=item.stock_uom, original_qty=quantity,
        suggested_location=rule.location if rule else '', suggested_qty=quantity,
        actual_location='', actual_qty=0,
        priority=rule.priority if rule else 0, putaway_rule=rule.name if rule else '',
        status='PENDING_VERIFICATION' if rule else 'UNALLOCATED',
    )


def plan_allocations(doc, exclude_allocation=None, exclude_stock_entry=None):
    """Return location splits without changing any purchasing item rows."""
    plans = defaultdict(list)
    occupied = {}
    stock_items = doc.get_stock_items() if callable(getattr(doc, 'get_stock_items', None)) else None
    for item in doc.get('items') or []:
        if stock_items is not None and item.item_code not in stock_items:
            continue
        pending = _stock_quantity(item)
        if pending <= EPSILON or not item.warehouse or not item.item_code:
            continue
        # Fixed assets and non-stock purchases do not consume storage capacity.
        if item.get('is_fixed_asset') or item.get('is_stock_item') == 0:
            continue
        warehouse = item.warehouse
        if warehouse not in occupied:
            occupied[warehouse] = defaultdict(float, get_physical_quantities(warehouse))
            for key, qty in get_reserved_quantities(warehouse, exclude_receipt=doc.name, exclude_allocation=(exclude_allocation.get(warehouse) if isinstance(exclude_allocation, dict) else exclude_allocation), exclude_stock_entry=exclude_stock_entry).items():
                occupied[warehouse][key] += qty
        quantities = occupied[warehouse]
        _, rules = get_ordered_dimension_putaway_rules(item.item_code, doc.company, include_full=True, current=True, target_warehouse=warehouse)
        for rule in sorted(rules or [], key=lambda rule: (0 if rule.get('item_code') == item.item_code else 1, flt(rule.priority), rule.name)):
            if rule.warehouse != warehouse or not rule.get('location'):
                continue
            location = get_location(rule.location)
            if location.disabled or location.is_group or location.custom_warehouse != warehouse:
                continue
            if location.get('custom_restricted_item') and location.custom_restricted_item != item.item_code:
                continue
            shared = bool(rule.get('custom_no_item_restriction'))
            relevant = [(key, qty) for key, qty in quantities.items()
                        if key[1] == rule.location and (shared or key[0] == item.item_code)]
            unlimited = bool(rule.get('custom_no_capacity_restriction'))
            if not unlimited:
                if rule.get('stock_uom') and rule.stock_uom != item.stock_uom:
                    continue
                if any(key[2] != item.stock_uom and abs(qty) > EPSILON for key, qty in relevant):
                    continue
            free = pending if unlimited else max(flt(rule.stock_capacity) - sum(qty for _, qty in relevant), 0)
            quantity = min(pending, free)
            if quantity <= EPSILON:
                continue
            plans[warehouse].append(_allocation_row(doc, item, quantity, rule))
            quantities[(item.item_code, rule.location, item.stock_uom)] += quantity
            pending -= quantity
            if pending <= EPSILON:
                break
        if pending > EPSILON:
            plans[warehouse].append(_allocation_row(doc, item, pending))
    return dict(plans)


def prepare_receipt(doc):
    """Enable only draft/new-flow receipts; never rewrite historical submissions."""
    if doc.docstatus == 2 or getattr(doc, '_action', None) == 'update_after_submit':
        return
    if doc.docstatus == 0 or getattr(doc, '_action', None) == 'submit':
        enabled = not doc.get('is_return') or bool(doc.get('return_against') and frappe.db.get_value(
            'Purchase Receipt', doc.return_against, 'custom_wrr_allocation_enabled') and frappe.db.exists(
                'Storage Allocation', {'purchase_receipt': doc.return_against, 'docstatus': 1, 'status': 'Completed'}))
        doc.custom_wrr_allocation_enabled = int(enabled)
    if uses_allocation(doc):
        # Location belongs to the saved allocation; copying the bulk row's
        # location into SLE would count a receipt in both physical ledgers.
        doc.location = ''
        for item in doc.get('items') or []:
            item.location = ''
            item.from_location = ''


def linked_allocations(receipt):
    names = frappe.get_all('Storage Allocation', filters={'purchase_receipt': receipt},
                           order_by='warehouse asc', pluck='name')
    return [frappe.get_doc('Storage Allocation', name) for name in names]


@contextmanager
def managed_write():
    previous = frappe.flags.get('wrr_allocation_sync')
    frappe.flags.wrr_allocation_sync = True
    try:
        yield
    finally:
        frappe.flags.wrr_allocation_sync = previous


def _write(allocation, method):
    with managed_write():
        return getattr(allocation, method)(ignore_permissions=True) if method in {'save', 'insert', 'delete'} else getattr(allocation, method)()


def _set_managed(allocation):
    allocation.flags.wrr_allocation_sync = True
    allocation.flags.ignore_permissions = True
    return allocation


def sync_allocations(doc, require_complete=False):
    if not uses_allocation(doc):
        return []
    existing = linked_allocations(doc.name)
    lock_warehouses([item.warehouse for item in doc.get('items') or []] + [a.warehouse for a in existing])
    if doc.get('is_return'):
        plans = plan_return_allocations(doc)
    elif doc.get('apply_putaway_rule'):
        plans = plan_allocations(doc)
    else:
        plans = {}
    shortages = [row for rows in plans.values() for row in rows if row['status'] == 'UNALLOCATED']
    if require_complete and shortages:
        details = ', '.join(f"{row['item_code']}: {abs(row['suggested_qty']):g} {row['stock_uom']}" for row in shortages)
        frappe.throw(_('Cannot Receive WRR. Unallocated quantity: {0}. Add capacity or an eligible Putaway Rule, then save again.').format(details))
    by_warehouse = {a.warehouse: a for a in existing}
    result = []
    for warehouse in sorted(set(plans) | set(by_warehouse)):
        allocation = by_warehouse.get(warehouse)
        rows = plans.get(warehouse, [])
        if allocation and allocation.docstatus != 0:
            frappe.throw(_('Storage Allocation {0} is already submitted or cancelled.').format(allocation.name))
        if not allocation:
            allocation = frappe.get_doc(dict(doctype='Storage Allocation', purchase_receipt=doc.name,
                                             company=doc.company, warehouse=warehouse))
        _set_managed(allocation)
        allocation.company = doc.company
        allocation.posting_date = doc.posting_date
        allocation.posting_time = doc.posting_time
        allocation.transaction_type = 'Warehouse Receiving Report'
        allocation.status = 'Draft' if rows else 'Cancelled'
        allocation.set('locations', rows)
        allocation.set('items', [])
        allocation.set('references', [])
        totals = defaultdict(lambda: [0, 0])
        for row in rows:
            totals[(row['item_code'], row['stock_uom'])][0] += row['original_qty']
            if row['status'] != 'UNALLOCATED':
                totals[(row['item_code'], row['stock_uom'])][1] += row['suggested_qty']
        for (item, uom), (qty, allocated) in totals.items():
            allocation.append('items', dict(item_code=item, uom=uom, qty=qty,
                                           putaway_qty=allocated, remaining_qty=qty - allocated))
            allocation.append('references', dict(reference_doctype='Purchase Receipt', reference_name=doc.name,
                                                item_code=item, uom=uom, qty=qty))
        if warehouse in by_warehouse:
            _write(allocation, 'save')
        else:
            _write(allocation, 'insert')
        result.append(allocation)
    return result


def submit_allocations(doc):
    if not uses_allocation(doc):
        return
    for allocation in linked_allocations(doc.name):
        if allocation.status == 'Cancelled' and not allocation.locations:
            continue
        if allocation.docstatus != 0 or any(row.status == 'UNALLOCATED' for row in allocation.locations):
            frappe.throw(_('WRR allocation is incomplete or already submitted.'))
        _set_managed(allocation)
        allocation.status = 'Completed'
        allocation.completed_at = now_datetime()
        for row in allocation.locations:
            row.actual_location = row.suggested_location
            row.actual_qty = row.suggested_qty
            row.status = 'VERIFIED'
            row.user = frappe.session.user
            row.user_full_name = frappe.get_cached_value('User', frappe.session.user, 'full_name') or frappe.session.user
            row.scan_time = allocation.completed_at
        _write(allocation, 'submit')


def cancel_allocations(doc):
    if not uses_allocation(doc):
        return
    allocations = linked_allocations(doc.name)
    lock_warehouses(a.warehouse for a in allocations)
    for allocation in allocations:
        _set_managed(allocation)
        allocation.status = 'Cancelled'
        if allocation.docstatus == 1:
            _write(allocation, 'cancel')
        elif allocation.docstatus == 0:
            _write(allocation, 'save')


def delete_draft_allocations(doc):
    for allocation in linked_allocations(doc.name):
        if allocation.docstatus != 0:
            frappe.throw(_('WRR has historical Storage Allocations and cannot be deleted.'))
        _set_managed(allocation)
        _write(allocation, 'delete')


@frappe.whitelist()
def get_wrr_allocations(purchase_receipt):
    doc = frappe.get_doc('Purchase Receipt', purchase_receipt)
    doc.check_permission('read')
    from qcmc_logic.utils import check_warehouse_access
    result = []
    for allocation in linked_allocations(doc.name):
        if not check_warehouse_access(frappe.session.user, allocation.warehouse):
            frappe.throw(_('You do not have access to Warehouse {0}.').format(allocation.warehouse), frappe.PermissionError)
        result.append(dict(name=allocation.name, warehouse=allocation.warehouse, docstatus=allocation.docstatus,
                           status=allocation.status, rows=[dict(
                               allocation_row=r.name, item_code=r.item_code, stock_uom=r.stock_uom, source_row=r.source_row,
                               location=r.actual_location if r.status == 'VERIFIED' else r.suggested_location,
                               quantity=r.actual_qty if r.status == 'VERIFIED' else r.suggested_qty,
                               priority=r.priority, putaway_rule=r.putaway_rule, status=r.status,
                           ) for r in allocation.locations]))
    return result


def plan_return_allocations(doc):
    """Withdraw from the referenced receipt's saved locations, never inbound rules."""
    plans = defaultdict(list)
    available_by_warehouse = {}
    prior = frappe.db.sql('''
        select wal.return_against_allocation, -wal.actual_qty as quantity
        from `tabWarehouse Allocation Location` wal
        inner join `tabStorage Allocation` wa on wa.name = wal.parent
        inner join `tabPurchase Receipt` receipt on receipt.name = wa.purchase_receipt
        where wa.docstatus = 1 and wa.status = 'Completed'
          and receipt.return_against = %s
          and coalesce(wal.return_against_allocation, '') != ''
        for update
    ''', doc.return_against, as_dict=True)
    returned = defaultdict(float)
    for row in prior:
        returned[row.return_against_allocation] += flt(row.quantity)
    originals = {a.warehouse: a for a in linked_allocations(doc.return_against) if a.docstatus == 1}
    stock_items = doc.get_stock_items() if callable(getattr(doc, 'get_stock_items', None)) else None
    for item in doc.get('items') or []:
        if (stock_items is not None and item.item_code not in stock_items) or item.get('is_fixed_asset'):
            continue
        pending = abs(_stock_quantity(item))
        if pending <= EPSILON:
            continue
        original = originals.get(item.warehouse)
        candidates = [r for r in original.locations if r.source_row == item.get('purchase_receipt_item')
                      and r.item_code == item.item_code] if original else []
        if item.warehouse not in available_by_warehouse:
            available_by_warehouse[item.warehouse] = get_physical_quantities(item.warehouse)
        available = available_by_warehouse[item.warehouse]
        for source in candidates:
            key = (item.item_code, source.actual_location, item.stock_uom)
            quantity = min(pending, max(flt(source.actual_qty) - returned.get(source.name, 0), 0),
                           max(available.get(key, 0), 0))
            if quantity <= EPSILON:
                continue
            rule = frappe._dict(name=source.putaway_rule, location=source.actual_location, priority=source.priority)
            row = _allocation_row(doc, item, -quantity, rule)
            row['return_against_allocation'] = source.name
            plans[item.warehouse].append(row)
            returned[source.name] = returned.get(source.name, 0) + quantity
            available[key] -= quantity
            pending -= quantity
        if pending > EPSILON:
            plans[item.warehouse].append(_allocation_row(doc, item, -pending))
    return dict(plans)


def get_allocation_grid_rows(doc):
    """Computed ERPNext table; Storage Allocation remains the sole stored plan."""
    if doc.is_new() or not uses_allocation(doc):
        return []
    if not doc.get('is_return') and not doc.get('apply_putaway_rule'):
        return []
    statuses = {'VERIFIED': 'Allocated', 'UNALLOCATED': 'Unallocated'}
    return [dict(name=row['allocation_row'], item_code=row['item_code'],
                 location=row['location'], stock_quantity=row['quantity'], stock_uom=row['stock_uom'],
                 priority=row['priority'], putaway_rule=row['putaway_rule'],
                 status=statuses.get(row['status'], 'Reserved'), warehouse=allocation['warehouse'],
                 warehouse_allocation=allocation['name'], source_row=row['source_row'])
            for allocation in get_wrr_allocations(doc.name) for row in allocation['rows']]
