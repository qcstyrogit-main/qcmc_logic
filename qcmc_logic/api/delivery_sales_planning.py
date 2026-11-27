"""Sales-only planning over the canonical SO Delivery Schedule ledger."""
from decimal import Decimal
import frappe
from frappe import _
from frappe.utils import getdate, now_datetime, today, flt
from qcmc_logic.api import delivery_schedule_service as service
from qcmc_logic.api import delivery_schedule_collaboration_v2 as collaboration
from qcmc_logic.api.sales_order_delivery_eligibility import is_open_sales_order_for_delivery


def require_endorsed(row):
    if row.get("endorsement_status") != "Endorsed":
        frappe.throw(_("Sales must endorse this schedule before Logistics or DR processing."))


def clear_review(row):
    # Preserve Sales instructions and the return evidence; invalidate previous approvals.
    for field in ("sales_proposed_qty", "logistics_committed_qty", "logistics_reason",
                  "logistics_remarks", "logistics_transfer_qty", "logistics_destination_date",
                  "final_qty", "sales_confirmed_by", "logistics_confirmed_by", "finalized_at"):
        row.set(field, None)
    row.confirmation_status = "Pending"


def mark_returned(row, reason, logistics_reason=None, logistics_remarks=None):
    clear_review(row)
    row.endorsement_status = "Returned"
    row.returned_by = frappe.session.user
    row.returned_at = now_datetime()
    row.return_reason = reason
    if logistics_reason:
        row.logistics_reason = logistics_reason
    if logistics_remarks:
        row.logistics_remarks = logistics_remarks
    collaboration._save(row)
    row.add_comment("Info", _("Returned to Sales: {0}").format(reason))


def _check_scope(so, item, transact=False):
    so.check_permission("read")
    if not frappe.has_permission("Company", "read", so.company):
        frappe.throw(_("Company access is required."), frappe.PermissionError)
    if not is_open_sales_order_for_delivery(so) or so.custom_so_type != "REGULAR":
        frappe.throw(_("Only approved open Regular Sales Orders can be planned."))
    if (not item.warehouse or item.get("delivered_by_supplier")
            or frappe.db.get_value("Warehouse", item.warehouse, "company") != so.company
            or frappe.db.get_value("Warehouse", item.warehouse, "custom_is_province")):
        frappe.throw(_("Item requires a permitted non-provincial warehouse."))
    collaboration._validate_scope(so, item, "Sales", transact=transact)


def _history_block(item, state):
    rows = state["schedules"]
    if any(row.history_status != "Verified" for row in rows):
        return _("Reconcile historical schedules before planning")
    roots = sum((Decimal(str(row.original_qty or 0)) for row in rows), Decimal(0))
    if roots != state["planned_qty"] or roots > state["ordered_qty"]:
        return _("Original commitments do not match the current plan; reconcile first")
    return _("Legacy DN without schedule link") if _unlinked_dn_exists(item.name) else ""


def _unlinked_dn_exists(item_name):
    # Do not invent lineage or double-allocate legacy drafts or submitted deliveries.
    return bool(frappe.db.sql(collaboration._quoted_sql("""
        SELECT dni.name FROM [[BT]]tabDelivery Note Item[[BT]] dni
        JOIN [[BT]]tabDelivery Note[[BT]] dn ON dn.name = dni.parent
        WHERE dni.so_detail = %s AND dn.docstatus IN (0,1)
        AND IFNULL(dni.custom_so_delivery_schedule, '') = '' LIMIT 1
    """), item_name))


@frappe.whitelist()
def get_rows(company, delivery_date=None, warehouse=None, customer=None, include_future=0, start=0):
    collaboration._require_role("Sales")
    if not company or not frappe.has_permission("Company", "read", company):
        frappe.throw(_("Select a permitted company."), frappe.PermissionError)
    if warehouse and frappe.db.get_value("Warehouse", warehouse, "company") != company:
        frappe.throw(_("Warehouse does not belong to company."))
    target = getdate(delivery_date or today())
    all_dates = str(include_future) in ("1", "True", "true")
    filters = {"company": company, "docstatus": 1, "custom_so_type": "REGULAR",
               "status": ["in", ["To Deliver and Bill", "To Deliver", "To Bill"]]}
    if customer:
        filters["customer"] = customer
    start = max(0, int(start))
    orders = frappe.get_list("Sales Order", filters=filters, pluck="name",
        order_by="delivery_date asc, name asc", limit_start=start, limit_page_length=51)
    result = []
    for name in orders[:50]:
        so = frappe.get_doc("Sales Order", name)
        for item in so.items:
            if warehouse and item.warehouse != warehouse:
                continue
            if flt(item.qty) <= flt(item.delivered_qty):
                continue
            try:
                _check_scope(so, item)
            except (frappe.PermissionError, frappe.ValidationError):
                continue
            base = dict(sales_order=so.name, sales_order_item=item.name, customer=so.customer,
                customer_name=so.customer_name, item_code=item.item_code, item_name=item.item_name,
                warehouse=item.warehouse, uom=item.uom, ordered_qty=flt(item.qty),
                delivered_qty=flt(item.delivered_qty), so_modified=str(so.modified))
            schedules = frappe.get_all("SO Delivery Schedule", filters={"sales_order_item": item.name},
                fields=["name", "delivery_date", "original_promise_date", "original_qty", "current_total",
                        "planned_qty", "history_status", "endorsement_status", "modified",
                        "sales_remarks", "return_reason", "logistics_confirmed_by", "confirmation_status"],
                order_by="delivery_date asc, name asc")
            try:
                state = service.quantity_state(item.name, check_sales_access=False)
                blocked = _history_block(item, state)
            except frappe.ValidationError:
                state, blocked = None, "Inconsistent schedule allocations; reconcile first"
            for row in schedules:
                if not all_dates and getdate(row.delivery_date) > target:
                    continue
                available = float(state["available_scheduled_qty"].get(row.name, 0)) if state else flt(row.planned_qty)
                if available <= 0:
                    continue
                status = row.endorsement_status or "For Planning"
                active = bool(collaboration._has_dn_history(row.name))
                can_replace = False
                if active:
                    notes = frappe.get_all("Delivery Note Item", filters={"custom_so_delivery_schedule": row.name}, pluck="parent")
                    if notes:
                        statuses = frappe.get_all("Delivery Note", filters={"name": ["in", sorted(set(notes))]}, pluck="docstatus")
                        can_replace = bool(statuses) and all(int(status) == 2 for status in statuses)
                overdue = getdate(row.delivery_date) < getdate(today())
                can_edit = not blocked and row.history_status == "Verified" and not active and (
                    status != "Endorsed" or overdue)
                result.append(dict(base, **row, available_qty=available, has_dn_history=active,
                    status=status, can_edit=bool(can_edit), can_replace=can_replace and not blocked and row.history_status == "Verified", overdue=overdue, blocked_reason=blocked or (
                        "Reconciliation required" if row.history_status != "Verified" else
                        "Delivery Note history protected" if active else
                        "Already endorsed" if not can_edit else "")))
            if state and not blocked:
                available = state["available_to_schedule_qty"]
                due = getdate(item.delivery_date or so.delivery_date)
                if available > 0 and (all_dates or due <= target):
                    result.append(dict(base, name="unscheduled:" + item.name, delivery_date=str(due),
                        original_promise_date=str(due), original_qty=0, current_total=0,
                        available_qty=float(available), expected_planned_qty=float(state["planned_qty"]),
                        modified=str(so.modified), status="Unscheduled", can_edit=True,
                        overdue=due < getdate(today()), sales_remarks="", return_reason=""))
            elif blocked and (not any(r["sales_order_item"] == item.name for r in result)) and (all_dates or getdate(item.delivery_date or so.delivery_date) <= target):
                result.append(dict(base, name="unscheduled:" + item.name,
                    delivery_date=str(item.delivery_date or so.delivery_date), available_qty=0,
                    status="Blocked", can_edit=False, blocked_reason=blocked, overdue=getdate(item.delivery_date or so.delivery_date) < getdate(today())))
    return {"rows": result, "start": start, "has_more": len(orders) > 50}


def _plan(entry, endorse):
    name = entry.get("schedule")
    if not isinstance(name, str) or not name:
        frappe.throw(_("Missing schedule identity."))
    date = getdate(entry.get("delivery_date"))
    if not entry.get("delivery_date") or date < getdate(today()):
        frappe.throw(_("Choose today or a future operational date."))
    remarks = collaboration._clean_remarks(entry.get("remarks")) or _("Sales delivery planning")
    if name.startswith("unscheduled:"):
        so, item = service._load_so_item(name.split(":", 1)[1], lock=True)
        _check_scope(so, item, True)
        state = service.quantity_state(item.name, lock=True)
        if (str(so.modified) != str(entry.get("modified"))
                or service._snapshot_decimal(entry.get("expected_planned_qty")) != state["planned_qty"]):
            frappe.throw(_("Sales Order or schedule changed. Refresh."), frappe.TimestampMismatchError)
        blocked = _history_block(item, state)
        if blocked:
            frappe.throw(blocked)
        available = state["available_to_schedule_qty"]
        amount = service._decimal(entry.get("quantity"), state["precision"])
        if amount > available:
            frappe.throw(_("Quantity exceeds unscheduled demand."))
        # Establish remaining original demand using the existing SO promise date.
        # Subsequent dates are transfers, never new original commitments.
        initial = service.create_schedule(item.name, str(item.delivery_date or so.delivery_date),
            float(available), _("Original Sales Order delivery commitment"), str(so.modified),
            float(state["planned_qty"]))
        row = frappe.get_doc("SO Delivery Schedule", initial["schedule"])
    else:
        row, so, item = collaboration._load_locked(name, entry.get("modified"), "Sales")
        _check_scope(so, item, True)
        if collaboration._has_dn_history(row.name) or _unlinked_dn_exists(item.name):
            frappe.throw(_("Delivery Note history is protected. Use the authorized replacement or reconciliation action."))
        if row.endorsement_status == "Endorsed" and getdate(row.delivery_date) >= getdate(today()):
            frappe.throw(_("Withdraw the endorsement before editing this schedule."))
        state = service.quantity_state(item.name, lock=True)
        blocked = _history_block(item, state)
        if blocked:
            frappe.throw(blocked)
        available = state["available_scheduled_qty"].get(row.name, Decimal(0))
        amount = service._decimal(entry.get("quantity"), state["precision"])
        if amount > available:
            frappe.throw(_("Quantity exceeds the available schedule balance."))
    # A stale endorsed, undelivered row may be reclaimed; reset prior approval.
    clear_review(row)
    row.endorsement_status = "For Planning"
    collaboration._save(row)
    if amount != Decimal(str(row.current_total)) or date != getdate(row.delivery_date):
        row, _tx = service._transfer_to_new_schedule(row, so, item, amount, date,
            remarks, clear_source_confirmation=False)
    row.sales_remarks = remarks
    row.endorsement_status = "Endorsed" if endorse else "For Planning"
    if endorse:
        row.endorsed_by = frappe.session.user
        row.endorsed_at = now_datetime()
    collaboration._save(row)
    row.add_comment("Info", _("Endorsed to Logistics") if endorse else _("Sales schedule saved"))
    return {"schedule": row.name, "sales_order": so.name, "quantity": float(amount),
            "delivery_date": str(date), "endorsement_status": row.endorsement_status}


@frappe.whitelist(methods=["POST"])
def save_rows(rows, endorse=False):
    collaboration._require_role("Sales")
    rows = frappe.parse_json(rows) if isinstance(rows, str) else rows
    if not isinstance(rows, list) or not rows or len(rows) > 100:
        frappe.throw(_("Select between 1 and 100 schedule rows."))
    endorse = str(endorse) in ("1", "True", "true")
    names = [entry.get("schedule") for entry in rows if isinstance(entry, dict)]
    if len(names) != len(rows) or len(set(names)) != len(names):
        frappe.throw(_("Duplicate or invalid selections."))
    frappe.db.savepoint("sales_planning_batch")
    try:
        return [_plan(entry, endorse) for entry in sorted(rows, key=lambda e: e["schedule"])]
    except Exception:
        frappe.db.rollback(save_point="sales_planning_batch")
        raise


@frappe.whitelist(methods=["POST"])
def withdraw(schedule, expected_modified, reason):
    row, so, item = collaboration._load_locked(schedule, expected_modified, "Sales")
    if row.endorsement_status != "Endorsed" or collaboration._has_dn_history(row.name):
        frappe.throw(_("Only endorsed schedules without Delivery Note history can be withdrawn."))
    reason = collaboration._clean_remarks(reason)
    if not reason:
        frappe.throw(_("Enter a withdrawal reason."))
    mark_returned(row, reason)
    return {"schedule": row.name, "endorsement_status": row.endorsement_status}
