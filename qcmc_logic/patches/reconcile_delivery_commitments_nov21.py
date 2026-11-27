"""One-time, evidence-bound reconciliation of development commitments.

Never changes commercial SO values, DN quantities, stock, or accounting.
The erroneous initial movement remains in the append-only ledger.
"""
from decimal import Decimal

import frappe
from frappe.utils import getdate
from qcmc_logic.api.delivery_schedule_service import (
    append_schedule_movement, _schedule_promise_attributions,
)

# SO, SO line, source, destination, original movement, reduction movement,
# mistaken initial movement, original quantity, reallocated quantity, destination date.
CASES = (
    ("26-00038", "hbf39tfvvm", "qunsm7tgng", "7jbgftrmmb",
     "quo3stipmb", "saovs1879g", "7jc9ojq8jn", 20000, 10000, "2026-11-27"),
    ("26-00038", "hbfc3dseah", "quo5jli0ee", "7jc98ogtrb",
     "quonsghi67", "sapdv73uic", "7jc7p36nfc", 20000, 10000, "2026-11-27"),
    ("26-00039", "4tfj64jl9o", "50l70rhepm", "6becgvb56b",
     "50lt150rp4", "65ov2cpu2i", "6beb453veu", 1000, 500, "2026-11-25"),
)


def qty(value):
    return Decimal(str(value or 0))


def require(condition, message):
    if not condition:
        frappe.throw("Reconciliation stopped: " + message)


def execute(dry_run=True):
    require(frappe.local.site == "erp.qcstyro.local",
        "this audited correction is restricted to erp.qcstyro.local")
    require(frappe.session.user == "Administrator" or "System Manager" in frappe.get_roles(),
        "System Manager required")
    require(isinstance(dry_run, bool), "dry_run must be a Boolean")
    results = []
    frappe.db.savepoint("reconcile_nov21_commitments")
    try:
        for case in CASES:
            results.append(reconcile(case, dry_run))
    except Exception:
        frappe.db.rollback(save_point="reconcile_nov21_commitments")
        raise
    return {"dry_run": dry_run, "results": results}


def reconcile(case, dry_run):
    so_name, item_name, source_name, dest_name, initial_name, reduction_name, mistaken_name, ordered, moved, dest_date = case
    ordered, moved = qty(ordered), qty(moved)
    tx = "reconcile-nov21:" + dest_name
    frappe.db.sql("SELECT name FROM {0}tabSales Order{0} WHERE name = %s FOR UPDATE".format(chr(96)), so_name)
    so = frappe.get_doc("Sales Order", so_name)
    item = next((i for i in so.items if i.name == item_name), None)
    require(so.docstatus == 1 and item and qty(item.qty) == ordered, so_name + ": SO changed")
    frappe.db.sql("SELECT name FROM {0}tabSO Delivery Schedule{0} WHERE sales_order_item = %s ORDER BY name FOR UPDATE".format(chr(96)), item_name)
    rows = frappe.get_all("SO Delivery Schedule", filters={"sales_order_item": item_name}, pluck="name")
    require(set(rows) == {source_name, dest_name}, so_name + ": schedule set changed")
    src = frappe.get_doc("SO Delivery Schedule", source_name)
    dst = frappe.get_doc("SO Delivery Schedule", dest_name)
    due = getdate("2026-11-24")
    for row, total in ((src, ordered - moved), (dst, moved)):
        require(row.sales_order == so_name and row.sales_order_item == item_name
            and row.item_code == item.item_code and row.uom == item.uom
            and row.warehouse == item.warehouse and qty(row.conversion_factor) == qty(item.conversion_factor)
            and row.history_status == "Verified" and qty(row.current_total) == total
            and qty(row.planned_qty) == total, row.name + ": identity or quantity changed")
    require(getdate(src.delivery_date) == due and getdate(src.original_delivery_date) == due
        and getdate(src.original_promise_date) == due and qty(src.original_qty) == ordered
        and qty(src.original_promise_qty) == ordered and getdate(dst.delivery_date) == getdate(dest_date)
        and getdate(dst.original_delivery_date) == getdate(dest_date), so_name + ": dates or source original changed")
    initial = frappe.get_doc("Delivery Schedule Movement", initial_name)
    reduction = frappe.get_doc("Delivery Schedule Movement", reduction_name)
    mistaken = frappe.get_doc("Delivery Schedule Movement", mistaken_name)
    for movement in (initial, reduction, mistaken):
        require(movement.sales_order == so_name and movement.sales_order_item == item_name
            and movement.uom == item.uom, movement.name + ": evidence identity changed")
    require(initial.operation_type == "Initial Commitment" and initial.destination_schedule == src.name
        and initial.promise_commitment == src.name and qty(initial.promise_qty) == ordered
        and getdate(initial.promise_date) == due, initial.name + ": initial evidence changed")
    require(reduction.operation_type == "Quantity Adjustment" and reduction.source_schedule == src.name
        and not reduction.destination_schedule and reduction.promise_commitment == src.name
        and qty(reduction.promise_qty) == moved and getdate(reduction.promise_date) == due,
        reduction.name + ": reduction evidence changed")
    require(mistaken.operation_type == "Initial Commitment" and mistaken.destination_schedule == dst.name
        and mistaken.promise_commitment == dst.name and qty(mistaken.promise_qty) == moved
        and getdate(mistaken.promise_date) == getdate(dest_date)
        and initial.creation < reduction.creation < mistaken.creation, mistaken.name + ": replacement evidence changed")
    prior = frappe.get_all("Delivery Schedule Movement", filters={"sales_order_item": item_name},
        fields=["name", "idempotency_key", "transaction_id"])
    keys = {r.idempotency_key for r in prior if r.transaction_id == tx}
    expected_keys = {tx + ":reverse", tx + ":reattribute"}
    require(set(r.name for r in prior if r.transaction_id != tx) == {initial_name, reduction_name, mistaken_name},
        so_name + ": extra movement evidence; review manually")
    require(not keys or keys == expected_keys, so_name + ": incomplete prior reconciliation")
    # Check all submitted and draft allocations, including older postings, before changing lineage.
    allocations = frappe.db.sql("""
        SELECT dni.name, dni.custom_so_delivery_schedule AS schedule, dni.qty,
            dni.item_code, dni.uom, dni.conversion_factor, dni.against_sales_order,
            dn.docstatus, dn.company, dn.customer, dn.is_return
        FROM {0}tabDelivery Note Item{0} dni JOIN {0}tabDelivery Note{0} dn ON dn.name = dni.parent
        WHERE dni.so_detail = %s AND dn.docstatus IN (0,1)
    """.format(chr(96)), item_name, as_dict=True)
    active = {source_name: Decimal(0), dest_name: Decimal(0)}
    submitted = Decimal(0)
    for row in allocations:
        require(row.schedule in active and row.against_sales_order == so_name
            and row.item_code == item.item_code and row.uom == item.uom
            and qty(row.conversion_factor) == qty(item.conversion_factor)
            and row.company == so.company and row.customer == so.customer
            and not row.is_return and qty(row.qty) > 0, so_name + ": invalid active DN link")
        active[row.schedule] += qty(row.qty)
        if row.docstatus == 1:
            submitted += qty(row.qty)
    require(active[source_name] <= ordered - moved and active[dest_name] <= moved
        and submitted == qty(item.delivered_qty), so_name + ": fulfillment mismatch")
    expected_src = {(source_name, due): ordered - moved}
    expected_dst = {(source_name, due): moved}
    def balances(row):
        return {(root, getdate(date)): qty(amount)
            for (root, date), amount in _schedule_promise_attributions(row).items()}
    require(balances(src.name) == expected_src, so_name + ": source balance changed")
    if keys:
        require(qty(dst.original_qty) == 0 and qty(dst.original_promise_qty) == 0
            and qty(dst.quantity_changes) == moved and dst.source_schedule == src.name
            and getdate(dst.original_promise_date) == due and balances(dst.name) == expected_dst,
            so_name + ": prior correction no longer reconciles")
        return {"so": so_name, "item": item.item_code, "status": "Already reconciled"}
    require(qty(dst.original_qty) == moved and qty(dst.original_promise_qty) == moved
        and qty(dst.quantity_changes) == 0 and not dst.source_schedule
        and getdate(dst.original_promise_date) == getdate(dest_date)
        and balances(dst.name) == {(dst.name, getdate(dest_date)): moved},
        so_name + ": destination baseline changed")
    result = {"so": so_name, "item": item.item_code, "original_date": str(due),
        "original_qty": float(ordered), "reallocated_qty": float(moved),
        "destination_date": dest_date, "submitted_qty": float(submitted),
        "status": "Ready" if dry_run else "Reconciled"}
    if dry_run:
        return result
    # Explicit correction records: reverse only the erroneous attribution on the destination,
    # then attach the released source promise. No second operational transfer.
    reason = ("Development reconciliation of duplicate initial commitment. Original evidence: "
        + initial_name + ", " + reduction_name + ", " + mistaken_name
        + ". Reclassify destination as deferred original demand; no quantity/date change to the operational plan.")
    common = dict(operation_type="Quantity Adjustment", sales_order=so_name,
        sales_order_item=item_name, quantity=moved, promise_qty=moved, uom=item.uom,
        reason=reason, transaction_id=tx)
    append_schedule_movement(**common, promise_commitment=dst.name,
        promise_date=getdate(dest_date), source_schedule=dst.name,
        source_before=moved, source_after=moved, idempotency_key=tx + ":reverse")
    append_schedule_movement(**common, promise_commitment=src.name,
        promise_date=due, destination_schedule=dst.name,
        destination_before=moved, destination_after=moved, idempotency_key=tx + ":reattribute")
    # Controlled correction of erroneous derived origin fields; immutable evidence remains in ledger.
    frappe.db.set_value("SO Delivery Schedule", dst.name, {
        "original_qty": 0, "original_promise_qty": 0, "original_promise_date": due,
        "quantity_changes": float(moved), "source_schedule": src.name,
        "source_date": src.delivery_date, "movement_transaction_id": tx,
    })
    dst.reload()
    require(qty(dst.current_total) == moved and qty(dst.planned_qty) == moved
        and qty(dst.original_qty) + qty(dst.quantity_changes) == moved
        and balances(dst.name) == expected_dst and balances(src.name) == expected_src,
        so_name + ": post-reconciliation check failed")
    return result