"""Original-commitment service level. Current snapshot; posting date is a proxy."""
from collections import defaultdict
from decimal import Decimal

import frappe
from frappe import _
from frappe.utils import getdate, today

from qcmc_logic.api.delivery_schedule_service import _schedule_promise_attributions


def number(value, precision):
    return Decimal(str(value or 0)).quantize(Decimal(1).scaleb(-precision))


def evaluate(required, events, due, cutoff):
    """Events contain positive, non-overlapping attributed quantities."""
    delivered = sum((qty for date, qty in events if date <= cutoff), Decimal(0))
    timely = sum((qty for date, qty in events if date <= min(due, cutoff)), Decimal(0))
    if due >= cutoff:
        status = "Not Yet Due"
    elif timely >= required:
        status = "Pass"
    elif delivered >= required:
        status = "Delivered Late"
    elif delivered > 0:
        status = "Overdue Partial"
    else:
        status = "Overdue Undelivered"
    return {
        "delivered_qty": float(delivered), "on_time_qty": float(timely),
        "late_qty": float(delivered - timely), "open_qty": float(max(required - delivered, 0)),
        "on_time": "Yes" if delivered > 0 and delivered == timely else "No",
        "in_full": "Yes" if delivered >= required else "No",
        "otif": status,
    }


def allowed(doctype, name):
    return frappe.has_permission(doctype, "read", doc=name)


def execute(filters=None):
    filters = frappe._dict(filters or {})
    if "System Manager" not in frappe.get_roles() or not frappe.has_permission("Sales Order", "report"):
        frappe.throw(_("System Manager and Sales Order report permission required."), frappe.PermissionError)
    if not filters.from_date or not filters.to_date:
        frappe.throw(_("From Date and To Date are required."))
    start, end, cutoff = getdate(filters.from_date), getdate(filters.to_date), getdate(today())
    if start > end:
        frappe.throw(_("From Date must not exceed To Date."))
    if filters.company and not allowed("Company", filters.company):
        frappe.throw(_("Company access required."), frappe.PermissionError)

    # Include no-schedule SO lines and original commitments outside the SO header date.
    candidates = set(frappe.get_all("SO Delivery Schedule", filters={
        "original_promise_date": ["between", [start, end]]}, pluck="sales_order"))
    candidates.update(frappe.get_all("Sales Order Item", filters={
        "delivery_date": ["between", [start, end]], "parenttype": "Sales Order"}, pluck="parent"))
    candidates.update(frappe.get_all("Sales Order", filters={
        "delivery_date": ["between", [start, end]], "docstatus": 1}, pluck="name"))
    if filters.sales_order:
        candidates.intersection_update({filters.sales_order})
    data = []
    so_filters = {"docstatus": 1, "custom_so_type": "REGULAR"}
    if filters.company:
        so_filters["company"] = filters.company
    if filters.customer:
        so_filters["customer"] = filters.customer
    if candidates:
        so_filters["name"] = ["in", sorted(candidates)]
        visible = frappe.get_list("Sales Order", filters=so_filters, pluck="name", limit_page_length=0)
        for name in visible:
            so = frappe.get_doc("Sales Order", name)
            if not so.has_permission("read") or not allowed("Company", so.company):
                continue
            data.extend(order_rows(so, filters, start, end, cutoff))

    data.sort(key=lambda r: (r["promise_date"], r["company"], r["sales_order"], r["item_code"], r.get("commitment") or ""))
    eligible = [r for r in data if r["otif"] in ("Pass", "Delivered Late", "Overdue Partial", "Overdue Undelivered")]
    passed = sum(r["otif"] == "Pass" for r in eligible)
    exceptions = sum(r["otif"] == "Unreconciled" for r in data)
    summary = [
        {"label": _("OTIF (verified due commitments)"), "value": round(100 * passed / len(eligible), 2) if eligible else None, "datatype": "Percent"},
        {"label": _("Due commitments"), "value": len(eligible), "datatype": "Int"},
        {"label": _("Passed"), "value": passed, "datatype": "Int", "indicator": "Green"},
        {"label": _("Failed"), "value": len(eligible) - passed, "datatype": "Int", "indicator": "Red"},
        {"label": _("Exception rows"), "value": exceptions, "datatype": "Int", "indicator": "Orange"},
    ]
    message = _("Current snapshot of submitted regular Sales Orders. Original promise date selects period; "
        "today is not yet due. Submitted non-return DN posting date is a document-date proxy, not proof of customer receipt. "
        "Drafts and canceled DNs are excluded from fulfillment. Exceptions and future commitments are excluded from OTIF. "
        "Only orders and related documents readable by the current user are included. No mixed-UOM quantity total. "
        "Original baseline is the initial schedule commitment; no retrospective approval-date reconstruction.")
    return get_columns(), data, message, None, summary, 1


def order_rows(so, filters, start, end, cutoff):
    schedules = frappe.get_all("SO Delivery Schedule", filters={"sales_order": so.name}, fields=[
        "name", "sales_order_item", "item_code", "uom", "conversion_factor", "original_qty",
        "original_delivery_date", "original_promise_date", "original_promise_qty", "current_total",
        "delivery_date", "history_status", "source_schedule"], limit_page_length=0)
    # All relevant documents must be visible, or skip the order rather than report false failures.
    if any(not allowed("SO Delivery Schedule", s.name) for s in schedules):
        return []
    movements = frappe.get_all("Delivery Schedule Movement", filters={"sales_order": so.name}, fields=["name", "operation_type", "source_schedule", "destination_schedule", "sales_order_item", "promise_commitment", "promise_date", "promise_qty", "uom"], limit_page_length=0)
    if any(not allowed("Delivery Schedule Movement", m.name) for m in movements):
        return []
    dn_names = set(frappe.get_all("Delivery Note Item", filters={"against_sales_order": so.name}, pluck="parent"))
    if so.items:
        dn_names.update(frappe.get_all("Delivery Note Item", filters={"so_detail": ["in", [i.name for i in so.items]]}, pluck="parent"))
    if dn_names:
        return_names = set(frappe.get_all("Delivery Note", filters={
            "return_against": ["in", sorted(dn_names)], "docstatus": 1}, pluck="name"))
        dn_names.update(return_names)
    if any(not allowed("Delivery Note", n) for n in dn_names):
        return []
    notes = [frappe.get_doc("Delivery Note", name) for name in sorted(dn_names)]
    # A return without a reliable SO-item attribution is an order-wide evidence exception.
    has_return = any(d.docstatus == 1 and d.is_return for d in notes)
    data = []
    for item in so.items:
        if filters.item_code and item.item_code != filters.item_code:
            continue
        if item.get("delivered_by_supplier") or not allowed("Item", item.item_code):
            continue
        rows = [s for s in schedules if s.sales_order_item == item.name]
        roots = {s.name: s for s in rows if (s.original_qty or 0) > 0}
        fallback_date = getdate(item.delivery_date or so.delivery_date)
        if not (start <= fallback_date <= end or any(start <= getdate(s.original_promise_date or s.delivery_date) <= end for s in rows)):
            continue
        prec = item.precision("qty")
        q = lambda value: number(value, prec)
        base = {"company": so.company, "sales_order": so.name, "so_date": so.transaction_date,
            "so_delivery_date": so.delivery_date, "customer": so.customer, "customer_name": so.customer_name,
            "item_code": item.item_code, "item_name": item.item_name, "uom": item.uom,
            "sales_order_item": item.name}
        events = defaultdict(list)
        drs = defaultdict(set)
        delivery_notes = defaultdict(set)
        vehicles = defaultdict(set)
        dates = defaultdict(set)
        canceled = defaultdict(set)
        details = defaultdict(list)
        error = None
        if not roots or any(s.history_status != "Verified" for s in rows):
            error = "Missing or unreconciled schedule baseline"
        elif sum((q(s.original_qty) for s in roots.values()), Decimal(0)) != q(item.qty):
            error = "Original commitments do not reconcile to ordered quantity"
        elif has_return:
            error = "Submitted return: net fulfillment policy requires reconciliation"
        elif any(s.item_code != item.item_code or s.uom != item.uom or
                 Decimal(str(s.conversion_factor or 0)) != Decimal(str(item.conversion_factor or 0)) for s in rows):
            error = "Schedule item/UOM mismatch"
        elif any(not s.original_promise_date or q(s.original_promise_qty) != q(s.original_qty)
                 or getdate(s.original_promise_date) != getdate(s.original_delivery_date) for s in roots.values()):
            error = "Original promise evidence mismatch"

        if not error:
            for root, s in roots.items():
                initial = [m for m in movements if m.operation_type == "Initial Commitment" and m.destination_schedule == root]
                if (len(initial) != 1 or initial[0].promise_commitment != root or initial[0].sales_order_item != item.name
                    or initial[0].uom != item.uom or q(initial[0].promise_qty) != q(s.original_qty)
                    or getdate(initial[0].promise_date) != getdate(s.original_promise_date)):
                    error = "Missing or inconsistent initial commitment movement"
                    break
        balances = {}
        totals = defaultdict(Decimal)
        if not error:
            for s in rows:
                attrs = _schedule_promise_attributions(s.name)
                if any(root not in roots or getdate(date) != getdate(roots[root].original_promise_date)
                       for root, date in attrs):
                    error = "Unknown promise origin"
                    break
                balance = {root: q(qty) for (root, date), qty in attrs.items()}
                if sum(balance.values(), Decimal(0)) != q(s.current_total):
                    error = "Movement and schedule totals disagree"
                    break
                balances[s.name] = balance
                for root, qty in balance.items():
                    totals[root] += qty
                    dates[root].add(str(s.delivery_date))
            if not error and any(totals[root] != q(s.original_qty) for root, s in roots.items()):
                error = "Original commitment balance changed; attribution requires reconciliation"
        if not error:
            # Stable chronological allocation; never count a delivery twice.
            for dn in sorted(notes, key=lambda d: (getdate(d.posting_date), d.name)):
                if dn.docstatus not in (1, 2) or dn.is_return:
                    continue
                for line in dn.items:
                    if line.so_detail != item.name:
                        # Missing SO-line reference with matching item cannot be attributed safely.
                        if dn.docstatus == 1 and line.against_sales_order == so.name and not line.so_detail and line.item_code == item.item_code:
                            error = "Submitted DN without SO item reference"
                        continue
                    sid = line.get("custom_so_delivery_schedule")
                    if dn.docstatus == 2:
                        # A fully transferred schedule has zero current balance; use historical movement provenance.
                        historical_roots = {m.promise_commitment for m in movements if m.sales_order_item == item.name
                            and sid and sid in (m.source_schedule, m.destination_schedule) and m.promise_commitment in roots}
                        historical_roots.update(balances.get(sid, {}))
                        if sid in roots:
                            historical_roots.add(sid)
                        for root in historical_roots:
                            canceled[root].add(dn.get("custom_dr_number") or dn.name)
                        continue
                    if (sid not in balances or line.against_sales_order != so.name or line.item_code != item.item_code
                        or dn.company != so.company or dn.customer != so.customer or line.uom != item.uom
                        or Decimal(str(line.conversion_factor or 0)) != Decimal(str(item.conversion_factor or 0))
                        or q(line.qty) <= 0):
                        error = "Submitted DN missing valid schedule, identity or UOM"
                        break
                    remaining = q(line.qty)
                    for root in sorted(balances[sid], key=lambda k: (getdate(roots[k].original_promise_date), k)):
                        take = min(remaining, balances[sid][root])
                        if take <= 0:
                            continue
                        balances[sid][root] -= take
                        remaining -= take
                        events[root].append((getdate(dn.posting_date), take))
                        if getdate(dn.posting_date) <= cutoff:
                            dr = dn.get("custom_dr_number") or dn.name
                            drs[root].add(dr)
                            delivery_notes[root].add(dn.name)
                            details[root].append(f"{dr} ({dn.posting_date}): {take}")
                            vehicle = dn.get("vehicle_no")
                            if not vehicle and dn.get("delivery_trip") and allowed("Delivery Trip", dn.delivery_trip):
                                vehicle = frappe.db.get_value("Delivery Trip", dn.delivery_trip, "vehicle")
                            if vehicle:
                                vehicles[root].add(vehicle)
                    if remaining:
                        error = "Submitted quantity exceeds attributable schedule balance"
                        break
                if error:
                    break
            if not error and q(sum((qty for ev in events.values() for _, qty in ev), Decimal(0))) != q(item.delivered_qty):
                error = "Submitted DN quantity differs from Sales Order delivered quantity"

        if error:
            # Actual submitted evidence is independent of promise reconciliation.
            # Group by physical schedule, never guess which root owns a transfer.
            by_schedule = {s.name: s for s in rows}
            actual = defaultdict(list)
            for dn in notes:
                if dn.docstatus != 1 or dn.is_return or getdate(dn.posting_date) > cutoff:
                    continue
                if dn.company != so.company or dn.customer != so.customer:
                    continue
                for line in dn.items:
                    if (line.against_sales_order != so.name or line.so_detail != item.name
                        or line.item_code != item.item_code or line.uom != item.uom
                        or Decimal(str(line.conversion_factor or 0)) != Decimal(str(item.conversion_factor or 0))
                        or q(line.qty) <= 0):
                        continue
                    sid = line.get("custom_so_delivery_schedule")
                    actual[sid if sid in by_schedule else None].append((dn, q(line.qty)))
            candidates = set(roots) | set(actual)
            if not candidates:
                candidates.add(None)
            for sid in sorted(candidates, key=lambda k: k or ""):
                schedule = by_schedule.get(sid)
                due = getdate((schedule.original_promise_date or schedule.original_delivery_date or schedule.delivery_date)
                    if schedule else fallback_date)
                if not start <= due <= end:
                    continue
                entries = sorted(actual.get(sid, []), key=lambda entry: (getdate(entry[0].posting_date), entry[0].name))
                qty = sum((amount for _, amount in entries), Decimal(0))
                dr_numbers = sorted({dn.get("custom_dr_number") or dn.name for dn, _ in entries})
                vehicles = sorted({dn.get("vehicle_no") for dn, _ in entries if dn.get("vehicle_no")})
                detail = "; ".join(f"{dn.get('custom_dr_number') or dn.name} ({dn.posting_date}): {amount}" for dn, amount in entries)
                data.append(dict(base, commitment=sid, promise_date=due,
                    original_qty=float(q(schedule.original_qty)) if schedule else (float(q(item.qty)) if not roots else None),
                    revised_dates=str(schedule.delivery_date) if schedule else "",
                    delivered_qty=float(qty), dr_numbers=", ".join(dr_numbers), delivery_details=detail,
                    delivery_notes=", ".join(sorted({dn.name for dn, _ in entries})),
                    first_dr_date=getdate(entries[0][0].posting_date) if entries else None,
                    last_dr_date=getdate(entries[-1][0].posting_date) if entries else None,
                    vehicle_no=", ".join(vehicles), otif="Unreconciled",
                    evidence=error + "; DR Qty is gross submitted evidence, not verified original-promise attribution"))
            continue
        for root, s in roots.items():
            due = getdate(s.original_promise_date)
            if not start <= due <= end:
                continue
            required = q(s.original_qty)
            visible_events = sorted((date, qty) for date, qty in events[root] if date <= cutoff)
            cumulative = Decimal(0)
            completion = None
            for date, qty in visible_events:
                cumulative += qty
                if cumulative >= required:
                    completion = date
                    break
            data.append(dict(base, commitment=root, promise_date=due, original_qty=float(required),
                revised_dates=", ".join(sorted(dates[root])), dr_numbers=", ".join(sorted(drs[root])),
                delivery_details="; ".join(details[root]),
                delivery_notes=", ".join(sorted(delivery_notes[root])),
                vehicle_no=", ".join(sorted(vehicles[root])), canceled_dr_numbers=", ".join(sorted(canceled[root])),
                first_dr_date=visible_events[0][0] if visible_events else None,
                last_dr_date=visible_events[-1][0] if visible_events else None,
                completion_date=completion, delay_days=max((completion - due).days, 0) if completion else None,
                evidence="Submitted DN posting date",
                **evaluate(required, events[root], due, cutoff)))
    return data


def get_columns():
    specs = [
        ("company", "Company", "Link", "Company", 180),
        ("promise_date", "Original Schedule Date", "Date", None, 140),
        ("sales_order", "Sales Order", "Link", "Sales Order", 130),
        ("dr_numbers", "Valid DR Numbers", "Data", None, 180),
        ("delivery_notes", "Delivery Note(s)", "Data", None, 240),
        ("so_date", "SO Date", "Date", None, 100),
        ("so_delivery_date", "SO Delivery Date", "Date", None, 115),
        ("customer", "Customer", "Link", "Customer", 130),
        ("customer_name", "Customer Name", "Data", None, 180),
        ("item_code", "Item Code", "Link", "Item", 120),
        ("item_name", "Item Description", "Data", None, 180),
        ("uom", "UOM", "Link", "UOM", 70),
        ("commitment", "Original Schedule", "Link", "SO Delivery Schedule", 145),
        ("original_qty", "Original Qty", "Float", None, 120),
        ("revised_dates", "Operational Dates", "Data", None, 180),
        ("delivery_details", "DR Date / Attributed Qty", "Data", None, 320),
        ("first_dr_date", "First DR Date", "Date", None, 115),
        ("last_dr_date", "Last DR Date", "Date", None, 115),
        ("delivered_qty", "DR Qty", "Float", None, 110),
        ("on_time_qty", "On-Time Qty", "Float", None, 120),
        ("late_qty", "Late Qty", "Float", None, 110),
        ("open_qty", "Open Qty", "Float", None, 110),
        ("completion_date", "Completed Date", "Date", None, 120),
        ("delay_days", "Days Late", "Int", None, 90),
        ("on_time", "On Time", "Data", None, 95),
        ("in_full", "In Full", "Data", None, 95),
        ("otif", "OTIF Status", "Data", None, 160),
        ("vehicle_no", "Plate No.", "Data", None, 120),
        ("canceled_dr_numbers", "Canceled DR Numbers", "Data", None, 160),
        ("evidence", "Evidence / Exception", "Data", None, 320),
    ]
    return [dict(fieldname=field, label=_(label), fieldtype=kind, width=width,
        **({"options": options} if options else {})) for field, label, kind, options, width in specs]
