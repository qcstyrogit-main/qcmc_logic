"""Explicit one-off development dataset repair. Never register in patches.txt."""
from decimal import Decimal
import json
import traceback
from pathlib import Path

import frappe
from frappe.utils import getdate, now_datetime
from qcmc_logic.api import delivery_schedule_service as service

SITE = "erp.qcstyro.local"
COMPANY = "QC Styropackaging Corporation"
WAREHOUSE = "FG - Guyong"
NOTE = "Development dataset normalization; historical baseline is reconstructed for testing, not verified customer evidence."


def dec(value):
    return Decimal(str(value or 0))


def _guard():
    if frappe.local.site != SITE or frappe.session.user != "Administrator":
        frappe.throw("This repair is restricted to Administrator on " + SITE)
    wh = frappe.get_doc("Warehouse", WAREHOUSE)
    if wh.company != COMPANY or wh.is_group or wh.disabled:
        frappe.throw("Target warehouse is not an active QC leaf warehouse.")


def _notes(so):
    names = set(frappe.get_all("Delivery Note", filters={"custom_sales_order": so.name}, pluck="name"))
    names.update(frappe.get_all("Delivery Note Item", filters={"against_sales_order": so.name}, pluck="parent"))
    return [frappe.get_doc("Delivery Note", n) for n in sorted(names)]


def _schedule_rows(item):
    return [frappe.get_doc("SO Delivery Schedule", name) for name in frappe.get_all(
        "SO Delivery Schedule", filters={"sales_order_item": item.name}, pluck="name", order_by="delivery_date asc, name asc")]


def _dn_lines(so, item, notes):
    lines = []
    for dn in notes:
        if dn.docstatus == 2 or dn.is_return:
            continue
        for line in dn.items:
            if line.so_detail != item.name:
                continue
            if line.against_sales_order != so.name or line.item_code != item.item_code or line.uom != item.uom or dec(line.conversion_factor) != dec(item.conversion_factor) or dec(line.qty) <= 0:
                frappe.throw("DN line identity or quantity mismatch: " + line.name)
            lines.append((dn, line))
    return lines


def _set(doc, values):
    values = {key: value for key, value in values.items() if doc.get(key) != value}
    if values:
        frappe.db.set_value(doc.doctype, doc.name, values)
        doc.update(values)
    return bool(values)


def _preflight(so, notes):
    changing = {i.name for i in so.items if i.warehouse != WAREHOUSE}
    if changing and frappe.db.exists("DocType", "Stock Reservation Entry"):
        if frappe.db.exists("Stock Reservation Entry", {"voucher_no": so.name, "docstatus": 1}):
            frappe.throw("Active stock reservation requires separate handling")
    for dn in notes:
        if dn.company != COMPANY or dn.is_return:
            frappe.throw("Cross-company or return DN needs separate handling: " + dn.name)
        if dn.docstatus == 2:
            continue
        for line in dn.items:
            if line.against_sales_order != so.name:
                frappe.throw("Mixed or missing SO identity on linked DN: " + dn.name)
            if line.warehouse != WAREHOUSE:
                if dn.docstatus == 1 or frappe.db.exists("Stock Ledger Entry", {"voucher_type": "Delivery Note", "voucher_no": dn.name}):
                    frappe.throw("Posted stock must not be rewritten: " + dn.name)
                if line.get("serial_and_batch_bundle") or line.get("serial_no") or line.get("batch_no"):
                    frappe.throw("Serial/batch allocation requires separate handling: " + dn.name)
                if frappe.db.exists("Sales Invoice Item", {"dn_detail": line.name, "docstatus": 1}):
                    frappe.throw("Submitted invoice references changed DN item: " + dn.name)
        for line in getattr(dn, "packed_items", []):
            if line.warehouse != WAREHOUSE and dn.docstatus == 1:
                frappe.throw("Posted packed item warehouse cannot be rewritten: " + dn.name)


def _new_schedule(so, item, qty, date):
    previous = frappe.flags.get("delivery_schedule_service_write")
    frappe.flags.delivery_schedule_service_write = True
    try:
        return frappe.get_doc(dict(doctype="SO Delivery Schedule", sales_order=so.name,
            sales_order_item=item.name, item_code=item.item_code, warehouse=WAREHOUSE,
            delivery_date=date, planned_qty=float(qty), uom=item.uom,
            conversion_factor=item.conversion_factor, remarks=NOTE)).insert(ignore_permissions=True)
    finally:
        frappe.flags.delivery_schedule_service_write = previous


def _baseline(row, item, amount):
    date = row.original_delivery_date or row.delivery_date
    _set(row, dict(original_delivery_date=date, original_promise_date=date,
        original_qty=float(amount), original_promise_qty=float(amount), planned_qty=float(amount),
        current_total=float(amount), quantity_changes=0, history_status="Verified",
        endorsement_status="For Planning", confirmation_status="Pending",
        sales_confirmed_by=None, logistics_confirmed_by=None, final_qty=0, finalized_at=None,
        sales_proposed_qty=0, logistics_committed_qty=0, logistics_transfer_qty=0,
        remarks=NOTE))
    if amount:
        service.append_schedule_movement(operation_type="Initial Commitment", sales_order=row.sales_order,
            sales_order_item=item.name, quantity=amount, uom=item.uom, promise_date=date,
            promise_qty=amount, promise_commitment=row.name, destination_schedule=row.name,
            destination_before=0, destination_after=amount, reason=NOTE,
            idempotency_key="initial:" + row.name)


def _repair_item(so, item, notes, changes, archive):
    rows = _schedule_rows(item)
    lines = _dn_lines(so, item, notes)
    total_dn = sum((dec(line.qty) for dn, line in lines), Decimal(0))
    submitted = sum((dec(line.qty) for dn, line in lines if dn.docstatus == 1), Decimal(0))
    if total_dn > dec(item.qty) or submitted != dec(item.delivered_qty):
        frappe.throw("DN allocations/actual delivery do not match SO item: " + item.name)
    if so.docstatus != 1 and not rows:
        return
    if not rows and so.custom_so_type != "REGULAR" and not lines:
        return
    if item.get("delivered_by_supplier"):
        return
    if dec(item.qty) <= 0:
        return
    if any(r.history_status != "Verified" for r in rows):
        if any(r.history_status == "Verified" for r in rows) or frappe.db.exists("Delivery Schedule Movement", {"sales_order_item": item.name}):
            frappe.throw("Mixed verified/unverified history: " + item.name)
        amounts = []
        for r in rows:
            linked = sum((dec(l.qty) for dn, l in lines if l.get("custom_so_delivery_schedule") == r.name), Decimal(0))
            amounts.append(max(dec(r.planned_qty), linked))
        if sum(amounts) > dec(item.qty):
            frappe.throw("Historical planned quantity exceeds order: " + item.name)
        for r, amount in zip(rows, amounts):
            _baseline(r, item, amount)
            changes["historical_schedules"] += 1
    elif so.name == "26-00027" and rows and sum(dec(r.original_qty) for r in rows) != sum(dec(r.current_total) for r in rows):
        if lines or any(frappe.db.exists("Delivery Note Item", {"custom_so_delivery_schedule": r.name}) for r in rows) or any(dec(r.current_total) != 0 for r in rows):
            frappe.throw("Unexpected SO 26-00027 history; refusing test rebaseline")
        # Explicit development-only rebuild of this inconsistent test commitment.
        # Archive every former row and movement before replacing the invalid ledger.
        old = frappe.get_all("Delivery Schedule Movement", filters={"sales_order_item": item.name}, fields=["*"])
        archive.append(dict(sales_order=so.name, item=item.name, schedules=[r.as_dict() for r in rows], movements=old))
        frappe.db.delete("Delivery Schedule Movement", {"sales_order_item": item.name})
        for r in rows:
            _baseline(r, item, Decimal(0))
            changes["historical_schedules"] += 1
    rows = _schedule_rows(item)
    roots = sum((dec(r.original_qty) for r in rows), Decimal(0))
    planned = sum((dec(r.current_total) for r in rows), Decimal(0))
    if roots != planned or roots > dec(item.qty):
        frappe.throw("Existing promise conservation mismatch: " + item.name)
    if planned < dec(item.qty):
        _new_schedule(so, item, dec(item.qty) - planned, str(item.delivery_date or so.delivery_date))
        changes["new_baselines"] += 1
    # Every active DN allocation has one exact SO item, and a dedicated schedule
    # is created by moving existing promise attribution, not adding demand.
    for dn, line in lines:
        if line.get("custom_so_delivery_schedule"):
            continue
        if dn.docstatus != 0:
            frappe.throw("Unlinked submitted DN requires separate historical review: " + dn.name)
        state = service.quantity_state(item.name, lock=True, check_sales_access=False, allow_draft=so.docstatus == 0)
        candidates = [r for r in _schedule_rows(item)
            if not frappe.db.exists("Delivery Note Item", {"custom_so_delivery_schedule": r.name})
            and state["available_scheduled_qty"].get(r.name, Decimal(0)) >= dec(line.qty)]
        if not candidates:
            frappe.throw("No single unallocated promise can cover DN line: " + line.name)
        source = candidates[0]
        amount = dec(line.qty)
        if dec(source.current_total) == amount:
            allocated = source
        else:
            allocated, tx = service._transfer_to_new_schedule(source, so, item, amount, str(source.delivery_date), NOTE)
        _set(allocated, dict(endorsement_status="Endorsed"))
        _set(line, dict(custom_so_delivery_schedule=allocated.name))
        changes["linked_dn_items"] += 1
    for dn, line in lines:
        linked_name = line.get("custom_so_delivery_schedule")
        if not linked_name:
            frappe.throw("Active DN still has no schedule: " + line.name)
        linked = frappe.get_doc("SO Delivery Schedule", linked_name)
        if linked.sales_order != so.name or linked.sales_order_item != item.name or linked.warehouse != WAREHOUSE:
            frappe.throw("Existing DN schedule reference is inconsistent: " + line.name)
        _set(linked, {"endorsement_status": "Endorsed"})
    # Existing draft allocations may occupy only part of a historical schedule.
    # Keep linked quantities untouched; return only the unallocated balance.
    state = service.quantity_state(item.name, lock=True, check_sales_access=False, allow_draft=so.docstatus == 0)
    for r in _schedule_rows(item):
        free = state["available_scheduled_qty"].get(r.name, Decimal(0))
        if free <= 0 or not frappe.db.exists("Delivery Note Item", {"custom_so_delivery_schedule": r.name}):
            continue
        active = sum((dec(l.qty) for dn, l in lines if l.get("custom_so_delivery_schedule") == r.name), Decimal(0))
        # The in-memory notes can be stale after linking, use authoritative state.
        allocated = state["draft_allocated_by_schedule"].get(r.name, Decimal(0)) + state["submitted_by_schedule"].get(r.name, Decimal(0))
        if allocated <= 0:
            continue
        destination, tx = service._transfer_to_new_schedule(r, so, item, free, str(r.delivery_date), NOTE,
            clear_source_confirmation=False, allow_protected=True)
        _set(destination, {"endorsement_status": "For Planning"})
        changes["released_balances"] += 1
    final = service.quantity_state(item.name, check_sales_access=False, allow_draft=so.docstatus == 0)
    final_rows = _schedule_rows(item)
    if sum(dec(r.original_qty) for r in final_rows) != dec(item.qty) or final["planned_qty"] != dec(item.qty):
        frappe.throw("Post-repair quantity conservation failed: " + item.name)
    for r in final_rows:
        if sum(service._schedule_promise_attributions(r.name).values(), Decimal(0)) != dec(r.current_total):
            frappe.throw("Post-repair promise attribution failed: " + r.name)


def execute(dry_run=True, sales_orders=None, strict=False):
    _guard()
    if type(dry_run) is not bool or type(strict) is not bool:
        frappe.throw("dry_run and strict must be True or False")
    filters = {"company": COMPANY, "docstatus": ["in", [0, 1]]}
    if sales_orders is not None:
        if not isinstance(sales_orders, (list, tuple)) or not sales_orders or any(not isinstance(name, str) or not name for name in sales_orders):
            frappe.throw("Provide a nonempty list of Sales Order names.")
        filters["name"] = ["in", sorted(set(sales_orders))]
    orders = frappe.get_all("Sales Order", filters=filters,
        fields=["name", "docstatus"], order_by="name asc")
    if sales_orders is not None and {row.name for row in orders} != set(sales_orders):
        frappe.throw("One or more requested Sales Orders are outside the permitted QC development scope.")
    output = {"site": SITE, "warehouse": WAREHOUSE, "dry_run": dry_run, "orders_in_scope": len(orders),
        "orders_changed": 0, "so_items_changed": 0, "schedule_warehouses_changed": 0,
        "dn_items_changed": 0, "dn_headers_changed": 0, "historical_schedules": 0,
        "new_baselines": 0, "linked_dn_items": 0, "released_balances": 0,
        "skipped": [], "archive_file": None}
    archive = []
    bins = set()
    for entry in orders:
        so = frappe.get_doc("Sales Order", entry.name)
        notes = _notes(so)
        try:
            _preflight(so, notes)
        except frappe.ValidationError as exc:
            if strict:
                raise
            output["skipped"].append({"sales_order": so.name, "reason": str(exc), "traceback": traceback.format_exc()})
            continue
        if dry_run:
            output["historical_schedules"] += frappe.db.count("SO Delivery Schedule", {"sales_order": so.name, "history_status": "Unreconciled"})
            output["linked_dn_items"] += sum(not i.get("custom_so_delivery_schedule") for dn in notes if dn.docstatus == 0 for i in dn.items)
            output["so_items_changed"] += sum(i.warehouse != WAREHOUSE and not i.get("delivered_by_supplier") for i in so.items)
            output["schedule_warehouses_changed"] += frappe.db.count("SO Delivery Schedule", {"sales_order": so.name, "warehouse": ["!=", WAREHOUSE]})
            output["dn_items_changed"] += sum(i.warehouse != WAREHOUSE for dn in notes if dn.docstatus == 0 for i in dn.items)
            output["dn_headers_changed"] += sum(dn.set_warehouse != WAREHOUSE for dn in notes if dn.docstatus == 0)
            output["orders_changed"] += int(so.set_warehouse != WAREHOUSE or any(i.warehouse != WAREHOUSE for i in so.items))
            continue
        frappe.db.savepoint("dev_delivery_order")
        before = {k: v for k, v in output.items() if isinstance(v, int) and not isinstance(v, bool)}
        archive_len = len(archive)
        local_bins = set()
        try:
            # Lock order and referenced documents before modifying the development fixture.
            so = frappe.get_doc("Sales Order", so.name, for_update=True)
            notes = [frappe.get_doc("Delivery Note", dn.name, for_update=True) for dn in notes]
            _preflight(so, notes)
            changed = _set(so, {"set_warehouse": WAREHOUSE})
            for i in so.items:
                if i.get("delivered_by_supplier"):
                    continue
                if i.warehouse != WAREHOUSE:
                    if so.docstatus == 1 and frappe.db.get_value("Item", i.item_code, "is_stock_item"):
                        if i.warehouse:
                            local_bins.add((i.item_code, i.warehouse))
                        local_bins.add((i.item_code, WAREHOUSE))
                    _set(i, {"warehouse": WAREHOUSE})
                    output["so_items_changed"] += 1
                    changed = True
            for i in getattr(so, "packed_items", []):
                if i.warehouse != WAREHOUSE:
                    if so.docstatus == 1 and frappe.db.get_value("Item", i.item_code, "is_stock_item"):
                        if i.warehouse:
                            local_bins.add((i.item_code, i.warehouse))
                        local_bins.add((i.item_code, WAREHOUSE))
                    _set(i, {"warehouse": WAREHOUSE})
            for name in frappe.get_all("SO Delivery Schedule", filters={"sales_order": so.name}, pluck="name"):
                r = frappe.get_doc("SO Delivery Schedule", name)
                if _set(r, {"warehouse": WAREHOUSE}):
                    output["schedule_warehouses_changed"] += 1
            for dn in notes:
                if dn.docstatus != 0:
                    continue
                if _set(dn, {"set_warehouse": WAREHOUSE}):
                    output["dn_headers_changed"] += 1
                for i in dn.items:
                    if _set(i, {"warehouse": WAREHOUSE}):
                        output["dn_items_changed"] += 1
                for i in getattr(dn, "packed_items", []):
                    _set(i, {"warehouse": WAREHOUSE})
            for i in so.items:
                if so.docstatus == 1 and so.status in ("To Deliver and Bill", "To Deliver", "To Bill") or frappe.db.exists("SO Delivery Schedule", {"sales_order_item": i.name, "history_status": "Unreconciled"}):
                    _repair_item(so, i, notes, output, archive)
            if changed:
                output["orders_changed"] += 1
            bins.update(local_bins)
        except Exception as exc:
            frappe.db.rollback(save_point="dev_delivery_order")
            for key, value in before.items():
                output[key] = value
            del archive[archive_len:]
            if strict:
                raise
            output["skipped"].append({"sales_order": so.name, "reason": str(exc), "traceback": traceback.format_exc()})
    if not dry_run:
        from erpnext.stock.utils import get_or_make_bin
        from erpnext.stock.stock_balance import get_reserved_qty
        for item_code, warehouse in sorted(bins):
            name = get_or_make_bin(item_code, warehouse)
            bin_doc = frappe.get_doc("Bin", name)
            bin_doc.reserved_qty = get_reserved_qty(item_code, warehouse) or 0
            bin_doc.set_projected_qty()
            frappe.db.set_value("Bin", name, {"reserved_qty": bin_doc.reserved_qty, "projected_qty": bin_doc.projected_qty})
        if archive:
            path = Path(frappe.get_site_path("private", "files", "dev_delivery_rebaseline_" + now_datetime().strftime("%Y%m%d_%H%M%S") + ".json"))
            path.write_text(json.dumps(archive, default=str, indent=2), encoding="utf-8")
            output["archive_file"] = str(path)
        frappe.clear_cache()
    return output
