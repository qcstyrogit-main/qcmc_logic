"""Sales/Logistics collaboration on V2 operational delivery schedules.

Schedule proposals and departmental approvals are stored on SO Delivery Schedule.
This module does not create Delivery Notes, post stock, or alter invoicing.
"""

from decimal import Decimal, InvalidOperation

import frappe
from frappe import _
from frappe.utils import flt, now_datetime

_SALES_ROLE = "Sales Coordinator"
_LOGISTICS_ROLE = "Stock Confirm User"
_VIEW_ROLES = {_SALES_ROLE, _LOGISTICS_ROLE, "Invoicing Clerk", "System Manager"}
_MAX_REMARKS = 1000


def _quoted_sql(statement):
    """Render quoted MariaDB identifiers without exposing raw quote tokens to the bridge."""
    return statement.replace("[[BT]]", chr(96))


def _has_role(role):
    return role in frappe.get_roles()


def _require_role(department):
    role = {"Sales": _SALES_ROLE, "Logistics": _LOGISTICS_ROLE}.get(department)
    if not role:
        frappe.throw(_("Choose Sales or Logistics."))
    if not _has_role(role):
        frappe.throw(_("{0} permission is required.").format(role), frappe.PermissionError)


def _validate_scope(so, item, department, *, transact):
    if department == "Sales":
        from qcmc_logic.api.sales_order_scheduling_service import _validate_sales_coordinator_access
        _validate_sales_coordinator_access(so, item, require_transact=transact)
    else:
        from qcmc_logic.api.delivery_confirmation_service import _validate_warehouse_access
        _validate_warehouse_access(item.warehouse, require_transact=transact)


def _load_locked(schedule, expected_modified, department):
    """Serialize on the SO before locking its schedule, then recheck the version."""
    _require_role(department)
    if not schedule or not expected_modified:
        frappe.throw(_("Schedule and its current modified timestamp are required."))
    # Resolve and lock the SO + schedule in one current-read query. A normal
    # get_value() here would establish a REPEATABLE READ snapshot before the
    # parent lock, allowing a waiter to read stale allocations after the lock.
    sources = frappe.db.sql(
        _quoted_sql("""
            SELECT s.sales_order, s.sales_order_item
            FROM [[BT]]tabSO Delivery Schedule[[BT]] s
            JOIN [[BT]]tabSales Order[[BT]] so ON so.name = s.sales_order
            WHERE s.name = %s
            FOR UPDATE
        """),
        schedule,
        as_dict=True,
    )
    if not sources:
        frappe.throw(_("Schedule was not found. Refresh the workbench."))
    source = sources[0]
    so = frappe.get_doc("Sales Order", source.sales_order)
    so.check_permission("read")
    if not frappe.has_permission("Company", "read", so.company):
        frappe.throw(_("Company read access is required."), frappe.PermissionError)
    if so.docstatus != 1 or so.get("is_return"):
        frappe.throw(_("Only active submitted Sales Orders are available for schedule collaboration."))
    from qcmc_logic.api.sales_order_delivery_eligibility import is_open_sales_order_for_delivery
    if not is_open_sales_order_for_delivery(so) or so.custom_so_type not in ("REGULAR",):
        frappe.throw(_("Only open, eligible FOB Sales Orders are available for schedule collaboration."))
    item = next((i for i in so.items if i.name == source.sales_order_item), None)
    if not item:
        frappe.throw(_("Original Sales Order Item could not be found."))
    if frappe.db.get_value("Warehouse", item.warehouse, "company") != so.company:
        frappe.throw(_("Sales Order warehouse does not belong to the company."))
    _validate_scope(so, item, department, transact=True)

    row = frappe.get_doc("SO Delivery Schedule", schedule)
    if (
        row.sales_order != so.name
        or row.sales_order_item != item.name
        or row.item_code != item.item_code
        or row.warehouse != item.warehouse
    ):
        frappe.throw(_("Schedule no longer matches its Sales Order Item."))
    if str(row.modified) != str(expected_modified):
        frappe.throw(
            _("Schedule changed in another session. Refresh before saving."),
            frappe.TimestampMismatchError,
        )
    _assert_verified_history(row)
    return row, so, item


def _assert_verified_history(row):
    if row.get("history_status") != "Verified":
        frappe.throw(_("Reconcile this historical schedule before changing or confirming it."))


def _has_dn_history(schedule):
    return bool(frappe.db.exists("Delivery Note Item", {"custom_so_delivery_schedule": schedule}))

def _assert_open(row, allow_logistics_correction=False):
    has_history = _has_dn_history(row.name)
    if row.confirmation_status == "Finalized" and not has_history and not allow_logistics_correction:
        frappe.throw(_("Reopen this finalized schedule before making changes."))
    if has_history and not allow_logistics_correction:
        frappe.throw(_("This schedule has a Delivery Note reference and cannot be changed or reallocated."))
    if allow_logistics_correction:
        from qcmc_logic.api.delivery_schedule_service import _has_protected_schedule_delivery
        if _has_protected_schedule_delivery(row.name):
            frappe.throw(_("Schedule quantities committed to a protected Delivery Note cannot be changed."))


def _parse_quantity(raw, item, planned):
    if raw is None or isinstance(raw, bool) or str(raw).strip() == "":
        frappe.throw(_("Enter a quantity."))
    try:
        amount = Decimal(str(raw))
        maximum = Decimal(str(planned))
        precision = item.precision("qty")
        quantum = Decimal(1).scaleb(-precision)
    except (InvalidOperation, TypeError, ValueError, OverflowError):
        frappe.throw(_("Enter a valid quantity."))
    if not amount.is_finite() or amount <= 0 or amount.quantize(quantum) != amount:
        frappe.throw(_("Quantity must be positive and use the Sales Order Item precision."))
    if amount > maximum:
        frappe.throw(_("Proposed quantity cannot exceed the planned quantity. Reschedule the balance first."))
    return amount


def _clean_remarks(value):
    if value is None:
        return ""
    if not isinstance(value, str):
        frappe.throw(_("Remarks must be text."))
    value = value.strip()
    if len(value) > _MAX_REMARKS:
        frappe.throw(_("Remarks cannot exceed {0} characters.").format(_MAX_REMARKS))
    return value


def _clean_logistics_reason(value):
    if value in (None, ""):
        return ""
    if not isinstance(value, str):
        frappe.throw(_("Choose a valid Logistics reason."))
    from qcmc_logic.api.delivery_confirmation_service import _get_logistics_reason_code_map
    if value not in _get_logistics_reason_code_map():
        frappe.throw(_("Choose a valid Logistics reason."))
    return value


def validate_sales_final_quantity(final_qty, logistics_confirmed_qty, item, schedule_total):
    """Sales may authorize less than Logistics confirmed, never more."""
    final = _parse_quantity(final_qty, item, schedule_total)
    confirmed = _parse_quantity(logistics_confirmed_qty, item, schedule_total)
    if final > confirmed:
        frappe.throw(_("Sales Final Qty cannot exceed Logistics Confirmed QTY."))
    return final


def _save(row):
    """Save through the authorized service; retain normal validations and version history."""
    previous = frappe.flags.get("delivery_schedule_service_write")
    frappe.flags.delivery_schedule_service_write = True
    try:
        row.save(ignore_permissions=True)
    finally:
        frappe.flags.delivery_schedule_service_write = previous


def _serialize(row):
    return {
        "schedule": row.name,
        "modified": str(row.modified),
        "planned_qty": flt(row.planned_qty),
        "original_qty": flt(row.original_qty),
        "quantity_changes": flt(row.quantity_changes),
        "current_total": flt(row.current_total),
        "original_promise_date": row.original_promise_date,
        "source_schedule": row.get("source_schedule"),
        "source_date": row.get("source_date"),
        "movement_transaction_id": row.get("movement_transaction_id"),
        "sales_proposed_qty": row.sales_proposed_qty,
        "sales_remarks": row.sales_remarks,
        "logistics_committed_qty": row.logistics_committed_qty,
        "logistics_remarks": row.logistics_remarks,
        "logistics_reason": row.get("logistics_reason") or "",
        "logistics_transfer_qty": row.get("logistics_transfer_qty"),
        "logistics_destination_date": row.get("logistics_destination_date"),
        "sales_confirmed_by": row.sales_confirmed_by,
        "logistics_confirmed_by": row.logistics_confirmed_by,
        "final_qty": row.final_qty,
        "confirmation_status": row.confirmation_status or "Pending",
        "finalized_at": row.finalized_at,
    }


def _save_commitment(schedule, expected_modified, department, quantity, remarks,
        transfer_qty=None, destination_date=None, reason_code=None):
    row, so, item = _load_locked(schedule, expected_modified, department)
    logistics_correction = department == "Logistics"
    confirmed_correction = logistics_correction and bool(row.get("logistics_confirmed_by"))
    _assert_open(row, allow_logistics_correction=logistics_correction)

    remarks = _clean_remarks(remarks)
    reason_code = _clean_logistics_reason(reason_code) if department == "Logistics" else None
    if (department == "Logistics" and reason_code
        and not frappe.db.has_column("SO Delivery Schedule", "logistics_reason")):
        frappe.throw(_("Run the SO Delivery Schedule Logistics Reason schema update before saving a reason."))
    if confirmed_correction and not remarks and not reason_code:
        frappe.throw(_("Enter a reason for the Logistics correction."))
    if department == "Logistics":
        if reason_code == "OK":
            if transfer_qty not in (None, "", 0, "0") or destination_date:
                frappe.throw(_("Good to go cannot include a date transfer."))
            if Decimal(str(quantity or 0)) != Decimal(str(row.current_total)):
                frappe.throw(_("Good to go must confirm the full scheduled quantity."))
        if reason_code in ("SA", "CR", "TO", "SE") and (
                transfer_qty not in (None, "", 0, "0") or destination_date):
            frappe.throw(_("This reason permits quantity changes only."))
        if reason_code in ("OR", "ND"):
            if not destination_date or Decimal(str(transfer_qty or 0)) != Decimal(str(row.current_total)):
                frappe.throw(_("Select a destination date to transfer the full schedule."))
    qty = None
    transfer_changed = False
    if department == "Logistics":
        if (transfer_qty in (None, "", 0, "0")) != (destination_date in (None, "")):
            frappe.throw(_("Enter both a positive transfer quantity and destination date."))
        if transfer_qty not in (None, "", 0, "0"):
            from qcmc_logic.api.delivery_schedule_service import quantity_state
            state = quantity_state(item.name, check_sales_access=False)
            transfer = _parse_quantity(transfer_qty, item, state["available_scheduled_qty"].get(row.name, 0))
            if not destination_date or str(destination_date) == str(row.delivery_date):
                frappe.throw(_("Choose a different destination date for the transfer."))
            expected_source_qty = Decimal(str(row.current_total or row.planned_qty or 0)) - transfer
            if quantity in (None, "") and expected_source_qty > 0:
                quantity = expected_source_qty
            if expected_source_qty == 0 and quantity in (None, "", 0, "0"):
                qty = Decimal(0)
            else:
                qty = _parse_quantity(quantity, item, row.planned_qty)
            if qty != expected_source_qty:
                frappe.throw(_("Logistics Confirmed QTY must equal the source Total remaining after the transfer."))
        else:
            qty = _parse_quantity(quantity, item, row.planned_qty)
            from qcmc_logic.api.delivery_schedule_service import quantity_state
            state = quantity_state(item.name, check_sales_access=False)
            reserved = Decimal(str(row.planned_qty or 0)) - Decimal(str(
                state["available_scheduled_qty"].get(row.name, 0)))
            if qty < reserved:
                frappe.throw(_("Logistics Confirmed QTY cannot fall below delivered or active DN allocations."))
        requested_transfer_qty = transfer if transfer_qty not in (None, "", 0, "0") else Decimal(0)
        requested_destination_date = destination_date or None
        transfer_changed = (Decimal(str(row.get("logistics_transfer_qty") or 0)) != requested_transfer_qty
            or str(row.get("logistics_destination_date") or "") != str(requested_destination_date or ""))
        row.logistics_transfer_qty = float(requested_transfer_qty)
        row.logistics_destination_date = requested_destination_date
    else:
        qty = _parse_quantity(quantity, item, row.planned_qty)
    qty_field = "sales_proposed_qty" if department == "Sales" else "logistics_committed_qty"
    remarks_field = "sales_remarks" if department == "Sales" else "logistics_remarks"
    same_reason = department != "Logistics" or (row.get("logistics_reason") or "") == reason_code

    existing = row.get(qty_field)
    same_qty = existing is not None and Decimal(str(existing)) == qty
    same_transfer = not transfer_changed
    if same_qty and same_transfer and same_reason and (row.get(remarks_field) or "") == remarks:
        return {**_serialize(row), "changed": False}

    row.set(qty_field, float(qty))
    row.set(remarks_field, remarks)
    if department == "Logistics":
        row.logistics_reason = reason_code
    # Sales changes require Sales to confirm again; Logistics confirmation remains
    # valid unless the operational commitment or transfer proposal changed.
    row.sales_confirmed_by = None
    if department == "Logistics":
        row.logistics_confirmed_by = None
    row.final_qty = None
    row.finalized_at = None
    row.confirmation_status = "In Review"
    _save(row)
    if confirmed_correction:
        row.add_comment("Info", _("Logistics correction saved by {0}: {1}").format(
            frappe.session.user, remarks or reason_code or _("No remarks supplied.")))
    return {**_serialize(row), "changed": True}


@frappe.whitelist(methods=["POST"])
def save_sales_proposal(schedule, expected_modified, quantity, remarks=""):
    """Only a Sales Coordinator can edit the Sales fields."""
    return _save_commitment(schedule, expected_modified, "Sales", quantity, remarks)


@frappe.whitelist(methods=["POST"])
def save_logistics_commitment(schedule, expected_modified, quantity, remarks="", transfer_qty=None,
        destination_date=None, reason_code=None):
    """Autosave and apply a Logistics edit as the confirmed commitment."""
    if schedule.startswith("unscheduled:"):
        schedule, expected_modified = _initialize_unscheduled_item(schedule.split(":", 1)[1], expected_modified)
    saved = _save_commitment(schedule, expected_modified, "Logistics", quantity, remarks,
        transfer_qty=transfer_qty, destination_date=destination_date, reason_code=reason_code)
    return _confirm(schedule, saved["modified"], "Logistics")


@frappe.whitelist(methods=["POST"])
def update_commitment(schedule, modified, department, quantity, remarks=""):
    """Compatibility entrypoint, with the same server-enforced departmental roles."""
    return _save_commitment(schedule, modified, department, quantity, remarks)


def _confirm(schedule, expected_modified, department):
    row, so, item = _load_locked(schedule, expected_modified, department)
    approved_field = "sales_confirmed_by" if department == "Sales" else "logistics_confirmed_by"
    if (department == "Sales" and row.get(approved_field) == frappe.session.user
            and row.confirmation_status == "Finalized" and not row.get("logistics_transfer_qty")):
        return {**_serialize(row), "changed": False}
    logistics_correction = department == "Logistics"
    _assert_open(row, allow_logistics_correction=logistics_correction)

    if department == "Logistics" and flt(row.get("logistics_transfer_qty")) > 0:
        if not row.get("logistics_destination_date"):
            frappe.throw(_("Choose a destination date before confirming the transfer."))
        from qcmc_logic.api.delivery_schedule_service import _apply_schedule_transfer_locked
        transfer_qty = row.logistics_transfer_qty
        transfer_date = row.logistics_destination_date
        transfer_reason = _clean_remarks(row.logistics_remarks) or row.get("logistics_reason")
        if not transfer_reason:
            frappe.throw(_("Enter Logistics remarks to authorize the transfer."))
        result = _apply_schedule_transfer_locked(row, so, item, transfer_qty, transfer_date,
            str(row.modified), transfer_reason, allow_finalized_correction=logistics_correction)
        source_doc = frappe.get_doc("SO Delivery Schedule", row.name)
        destination_doc = frappe.get_doc("SO Delivery Schedule", result["destination"])
        for target, confirmed_qty in ((source_doc, source_doc.current_total), (destination_doc, transfer_qty)):
            target.logistics_committed_qty = confirmed_qty
            target.logistics_confirmed_by = frappe.session.user
            target.logistics_transfer_qty = 0
            target.logistics_destination_date = None
            target.sales_confirmed_by = None
            target.final_qty = None
            target.finalized_at = None
            target.confirmation_status = "In Review"
            _save(target)
        return {**_serialize(source_doc), "changed": True,
            "transfer": {"source": row.name, "destination": destination_doc.name,
                "quantity": flt(transfer_qty), "transaction_id": result["transaction_id"]}}

    qty_field = "sales_proposed_qty" if department == "Sales" else "logistics_committed_qty"
    qty = row.get(qty_field)
    if qty is None or flt(qty) <= 0:
        frappe.throw(_("{0} must propose a positive quantity before confirming.").format(department))
    own_quantity = _parse_quantity(qty, item, row.planned_qty)
    if department == "Sales":
        if not row.get("logistics_confirmed_by"):
            frappe.throw(_("Logistics must confirm the schedule before Sales finalizes it."))
        own_quantity = validate_sales_final_quantity(
            qty, row.logistics_committed_qty, item, row.planned_qty
        )

    if row.get(approved_field) == frappe.session.user:
        return {**_serialize(row), "changed": False}

    if department == "Sales" and own_quantity < Decimal(str(row.planned_qty or 0)):
        # Sales confirmation is the transition that separates DR-authorized
        # quantity from still-open demand. Keep the remainder traceable now,
        # rather than waiting until someone requests a Draft Delivery Note.
        from qcmc_logic.api.delivery_schedule_service import _split_unfinalized_schedule_balance
        _split_unfinalized_schedule_balance(row, so, item, own_quantity, item.precision("qty"))

    row.set(approved_field, frappe.session.user)
    if department == "Sales":
        row.final_qty = float(own_quantity)
        row.finalized_at = now_datetime()
        row.confirmation_status = "Finalized"
    else:
        row.final_qty = None
        row.finalized_at = None
        row.confirmation_status = "In Review"
    _save(row)
    return {**_serialize(row), "changed": True}


@frappe.whitelist(methods=["POST"])
def confirm_sales(schedule, expected_modified):
    return _confirm(schedule, expected_modified, "Sales")


@frappe.whitelist(methods=["POST"])
def confirm_logistics(schedule, expected_modified):
    return _confirm(schedule, expected_modified, "Logistics")


@frappe.whitelist(methods=["POST"])
def confirm_commitment(schedule, modified, department):
    """Compatibility entrypoint, with server-enforced departmental role checks."""
    return _confirm(schedule, modified, department)


@frappe.whitelist(methods=["POST"])
def reopen_schedule(schedule, expected_modified, reason):
    """Reopen a finalized schedule only before any active DN allocation."""
    row, so, item = _load_locked(schedule, expected_modified, "Sales")
    if _has_dn_history(row.name):
        frappe.throw(_("Cannot reopen a schedule that has a Delivery Note reference. Create a separately authorized replacement schedule."))
    if row.confirmation_status != "Finalized":
        frappe.throw(_("Only finalized schedules need reopening."))
    reason = _clean_remarks(reason)
    if not reason:
        frappe.throw(_("Enter a reason for reopening the schedule."))
    row.sales_confirmed_by = None
    row.final_qty = None
    row.finalized_at = None
    row.confirmation_status = "In Review"
    row.remarks = "\n".join(filter(None, [row.remarks, _("Reopened by Sales: {0}").format(reason)]))
    _save(row)
    return {**_serialize(row), "changed": True}


@frappe.whitelist(methods=["POST"])
def authorize_cancelled_schedule_replacement(schedule, expected_modified, delivery_date, reason):
    """Move restored demand off a schedule with cancelled-DN history into a new pending schedule."""
    row, so, item = _load_locked(schedule, expected_modified, "Sales")
    reason = _clean_remarks(reason)
    if not reason:
        frappe.throw(_("Enter the replacement authorization reason."))
    from qcmc_logic.api.delivery_schedule_service import authorize_cancelled_schedule_replacement
    return authorize_cancelled_schedule_replacement(
        schedule, delivery_date, reason, str(row.modified)
    )


@frappe.whitelist(methods=["POST"])
def move_quantity(schedule, expected_modified, quantity, delivery_date, remarks):
    """Move only unallocated plan; schedule service owns locking and balance math."""
    row, so, item = _load_locked(schedule, expected_modified, "Sales")
    _assert_open(row)
    from qcmc_logic.api.delivery_schedule_service import redistribute_schedule
    return redistribute_schedule(
        schedule, quantity, delivery_date, str(row.modified), remarks
    )


@frappe.whitelist(methods=["POST"])
def add_schedule(sales_order_item, delivery_date, quantity, remarks, expected_so_modified, expected_planned_qty):
    """Create/merge a date bucket through the central schedule service."""
    from qcmc_logic.api.delivery_schedule_service import create_schedule
    return create_schedule(
        sales_order_item, delivery_date, quantity, remarks,
        expected_so_modified, expected_planned_qty,
    )


@frappe.whitelist(methods=["POST"])
def proceed_to_dr(schedules):
    """Sales creates Draft DN details from Logistics-confirmed schedules."""
    _require_role("Sales")
    if isinstance(schedules, str):
        schedules = frappe.parse_json(schedules)
    if not isinstance(schedules, list) or not schedules:
        frappe.throw(_("Select Logistics-confirmed schedule rows."))
    quantities, expected = {}, {}
    for entry in schedules:
        if (not isinstance(entry, dict) or not entry.get("schedule") or not entry.get("modified")
            or entry.get("draft_allocated_qty") is None):
            frappe.throw(_("Schedule identity, modified timestamp, and draft allocation snapshot are required."))
        name = entry["schedule"]
        if name in quantities:
            frappe.throw(_("Schedule {0} was selected more than once.").format(name))
        row, so, item = _load_locked(name, entry["modified"], "Sales")
        if not row.logistics_confirmed_by or row.logistics_committed_qty is None or flt(row.logistics_committed_qty) <= 0:
            frappe.throw(_("Schedule {0} needs a positive Logistics-confirmed quantity before Sales can create Delivery Note details.").format(name))
        from qcmc_logic.api.delivery_schedule_service import quantity_state
        state = quantity_state(item.name, lock=True)
        allocated = Decimal(str(state["draft_allocated_by_schedule"].get(name, 0)))
        if Decimal(str(entry["draft_allocated_qty"])) != allocated:
            frappe.throw(_("Draft allocations changed for schedule {0}. Refresh before creating Delivery Note details.").format(name), frappe.TimestampMismatchError)
        if row.confirmation_status == "Finalized" and row.sales_confirmed_by and row.final_qty is not None:
            quantity = Decimal(str(row.final_qty))
            if entry.get("quantity") not in (None, "") and _parse_quantity(entry["quantity"], item, row.planned_qty) != quantity:
                frappe.throw(_("Schedule {0} was already finalized at a different quantity. Reopen it before changing that amount.").format(name))
        else:
            requested = entry.get("quantity") if entry.get("quantity") not in (None, "") else row.logistics_committed_qty
            quantity = validate_sales_final_quantity(requested,
                row.logistics_committed_qty, item, row.planned_qty)
            if quantity < allocated:
                frappe.throw(_("Logistics-confirmed quantity for schedule {0} is below its existing Draft Delivery Note allocation.").format(name))
            if quantity < Decimal(str(row.planned_qty or 0)):
                from qcmc_logic.api.delivery_schedule_service import _split_unfinalized_schedule_balance
                _split_unfinalized_schedule_balance(row, so, item, quantity, item.precision("qty"))
            row.sales_proposed_qty = float(quantity)
            row.final_qty = float(quantity)
            row.sales_confirmed_by = frappe.session.user
            row.finalized_at = now_datetime()
            row.confirmation_status = "Finalized"
            _save(row)
        quantities[name] = float(quantity)
        expected[name] = {"modified": str(row.modified), "draft_allocated_qty": float(allocated)}

    from qcmc_logic.api.delivery_schedule_service import create_draft_delivery_notes
    return create_draft_delivery_notes(quantities, expected)


@frappe.whitelist()
def get_proceed_to_dr_preview(schedules):
    """Preview Delivery Note details for Logistics-confirmed schedules."""
    _require_role("Sales")
    if isinstance(schedules, str):
        schedules = frappe.parse_json(schedules)
    if not isinstance(schedules, list) or not schedules:
        frappe.throw(_("Select Logistics-confirmed schedule rows."))
    from qcmc_logic.api.delivery_schedule_service import quantity_state

    selected, snapshots, identities = [], {}, set()
    for entry in schedules:
        if not isinstance(entry, dict) or not entry.get("schedule") or not entry.get("modified"):
            frappe.throw(_("Schedule identity and current modified timestamp are required."))
        name = entry["schedule"]
        if name in identities:
            frappe.throw(_("Schedule {0} was selected more than once.").format(name))
        identities.add(name)
        row, so, item = _load_locked(name, entry["modified"], "Sales")
        if not row.logistics_confirmed_by or row.logistics_committed_qty is None or flt(row.logistics_committed_qty) <= 0:
            frappe.throw(_("Schedule {0} needs a positive Logistics-confirmed quantity before Sales can create Delivery Note details.").format(name))
        quantity = row.final_qty if row.confirmation_status == "Finalized" and row.sales_confirmed_by and row.final_qty is not None else row.logistics_committed_qty
        quantity = validate_sales_final_quantity(quantity, row.logistics_committed_qty, item, row.planned_qty)
        state = quantity_state(item.name)
        allocated = flt(state["draft_allocated_by_schedule"].get(name, 0))
        if entry.get("draft_allocated_qty") is not None and flt(entry["draft_allocated_qty"]) != allocated:
            frappe.throw(_("Draft allocations changed for schedule {0}. Refresh before previewing.").format(name), frappe.TimestampMismatchError)
        available = flt(state["available_scheduled_qty"].get(name, 0))
        if flt(quantity) > allocated + available:
            frappe.throw(_("Confirmed quantity for schedule {0} is no longer available. Refresh and reconcile the schedule.").format(name), frappe.TimestampMismatchError)
        if frappe.db.sql("""
            SELECT dni.name FROM `tabDelivery Note Item` dni
            JOIN `tabDelivery Note` dn ON dn.name = dni.parent
            WHERE dni.custom_so_delivery_schedule = %s AND dn.docstatus = 1 LIMIT 1
        """, name):
            frappe.throw(_("Schedule {0} is already linked to a submitted Delivery Note.").format(name))
        selected.append({"schedule": name, "modified": str(row.modified), "draft_allocated_qty": allocated,
            "sales_order": so.name, "customer": so.customer_name, "item_code": item.item_code,
            "item_name": item.item_name, "delivery_date": str(row.delivery_date),
            "final_qty": flt(quantity, item.precision("qty")), "logistics_confirmed_qty": flt(row.logistics_committed_qty), "uom": item.uom,
            "quantity_locked": row.confirmation_status == "Finalized" and bool(row.sales_confirmed_by),
            "warehouse": item.warehouse, "qty_to_add": max(0, flt(quantity) - allocated)})
        snapshots[(so.name, str(row.delivery_date))] = (so, item)

    omitted = []
    selected_by_order_date = {(r["sales_order"], r["delivery_date"], r["schedule"]) for r in selected}
    for so_name, date in sorted(snapshots):
        candidates = frappe.get_all("SO Delivery Schedule", filters={
            "sales_order": so_name, "delivery_date": date, "history_status": "Verified"},
            fields=["name", "sales_order_item", "modified", "final_qty", "sales_confirmed_by",
                "confirmation_status", "logistics_confirmed_by", "logistics_committed_qty"])
        for candidate in candidates:
            if (so_name, date, candidate.name) in selected_by_order_date:
                continue
            try:
                row, so, item = _load_locked(candidate.name, candidate.modified, "Sales")
            except frappe.PermissionError:
                continue
            if not row.logistics_confirmed_by or row.logistics_committed_qty is None or flt(row.logistics_committed_qty) <= 0:
                continue
            candidate_qty = row.final_qty if row.confirmation_status == "Finalized" and row.sales_confirmed_by and row.final_qty is not None else row.logistics_committed_qty
            candidate_qty = validate_sales_final_quantity(candidate_qty, row.logistics_committed_qty, item, row.planned_qty)
            state = quantity_state(item.name)
            allocated = flt(state["draft_allocated_by_schedule"].get(row.name, 0))
            omitted.append({"schedule": row.name, "sales_order": so.name, "customer": so.customer_name,
                "item_code": item.item_code, "item_name": item.item_name, "delivery_date": str(row.delivery_date),
                "final_qty": flt(candidate_qty, item.precision("qty")), "logistics_confirmed_qty": flt(row.logistics_committed_qty), "uom": item.uom,
                "warehouse": item.warehouse, "draft_allocated_qty": allocated,
                "qty_to_add": max(0, flt(candidate_qty) - allocated)})

    groups = {}
    for row in selected:
        key = (row["sales_order"], row["delivery_date"], row["warehouse"])
        group = groups.setdefault(key, {"sales_order": row["sales_order"], "customer": row["customer"],
            "delivery_date": row["delivery_date"], "warehouse": row["warehouse"], "items": []})
        group["items"].append({"schedule": row["schedule"], "item_code": row["item_code"],
            "item_name": row["item_name"], "final_qty": row["final_qty"],
            "logistics_confirmed_qty": row["logistics_confirmed_qty"], "quantity_locked": row["quantity_locked"], "uom": row["uom"],
            "draft_allocated_qty": row["draft_allocated_qty"], "qty_to_add": row["qty_to_add"]})
    return {"schedules": [{key: row[key] for key in ("schedule", "modified", "draft_allocated_qty")} for row in selected],
        "groups": list(groups.values()), "omitted": omitted}


@frappe.whitelist()
def get_schedule_rows(company, delivery_date=None, warehouse=None, limit=500, include_overdue=0):
    """Read V2 schedule commitments without exposing unauthorized SOs or warehouses."""
    if frappe.session.user != "Administrator" and not set(frappe.get_roles()).intersection(_VIEW_ROLES):
        frappe.throw(_("You are not authorized to view delivery schedules."), frappe.PermissionError)
    if not company or not frappe.has_permission("Company", "read", company):
        frappe.throw(_("Company read access is required."), frappe.PermissionError)
    try:
        limit = min(max(int(limit), 1), 500)
    except (TypeError, ValueError):
        frappe.throw(_("Invalid row limit."))
    conditions = [
        "so.company = %s",
        "so.docstatus = 1",
        "so.status IN ('To Deliver and Bill', 'To Deliver', 'To Bill')",
        "so.custom_so_type = 'REGULAR'",
    ]
    values = [company]
    if warehouse:
        if frappe.db.get_value("Warehouse", warehouse, "company") != company:
            frappe.throw(_("Warehouse does not belong to the selected company."))
        conditions.append("s.warehouse = %s")
        values.append(warehouse)
    if delivery_date:
        conditions.append("s.delivery_date <= %s" if str(include_overdue) in ("1", "True", "true") else "s.delivery_date = %s")
        values.append(delivery_date)
    values.append(limit)
    logistics_reason_sql = "s.logistics_reason" if frappe.db.has_column("SO Delivery Schedule", "logistics_reason") else "''"
    records = frappe.db.sql("""
        SELECT s.name, s.sales_order, s.sales_order_item, s.item_code, s.warehouse,
            s.delivery_date, s.planned_qty, s.original_qty, s.quantity_changes, s.current_total,
            s.original_promise_date, s.source_schedule, s.source_date, s.movement_transaction_id,
            s.uom, s.conversion_factor, s.remarks,
            s.sales_proposed_qty, s.sales_remarks, s.logistics_committed_qty,
            s.logistics_remarks, {logistics_reason_sql} AS logistics_reason,
            s.logistics_transfer_qty, s.logistics_destination_date,
            s.final_qty, s.confirmation_status,
            s.sales_confirmed_by, s.logistics_confirmed_by, s.finalized_at, s.history_status, s.modified
        FROM `tabSO Delivery Schedule` s
        JOIN `tabSales Order` so ON so.name = s.sales_order
        WHERE {conditions}
        ORDER BY s.delivery_date asc, s.name asc
        LIMIT %s
    """.format(conditions=" AND ".join(conditions), logistics_reason_sql=logistics_reason_sql),
        tuple(values), as_dict=True)
    result = []
    for row in records:
        so = frappe.get_cached_doc("Sales Order", row.sales_order)
        from qcmc_logic.api.sales_order_delivery_eligibility import is_open_sales_order_for_delivery
        if (so.company != company or not is_open_sales_order_for_delivery(so)
            or so.custom_so_type not in ("REGULAR",)
            ):
            continue
        if not frappe.has_permission("Sales Order", "read", doc=so):
            continue
        item = next((i for i in so.items if i.name == row.sales_order_item), None)
        if not item or item.warehouse != row.warehouse or item.item_code != row.item_code:
            continue

        can_sales = False
        can_logistics = False
        if _has_role(_SALES_ROLE):
            try:
                _validate_scope(so, item, "Sales", transact=False)
                can_sales = True
            except frappe.PermissionError:
                pass
        if _has_role(_LOGISTICS_ROLE):
            try:
                _validate_scope(so, item, "Logistics", transact=False)
                can_logistics = True
            except frappe.PermissionError:
                pass
        if not (can_sales or can_logistics):
            if not (_has_role("Invoicing Clerk") or _has_role("System Manager")):
                continue
            try:
                _validate_scope(so, item, "Logistics", transact=False)
            except frappe.PermissionError:
                continue
        result.append({
            **row,
            "customer": so.customer,
            "customer_name": so.customer_name,
            "ordered_qty": flt(item.qty),
            "delivered_qty": flt(item.delivered_qty),
            "qty_precision": item.precision("qty"),
            "can_edit_sales": can_sales and row.history_status == "Verified",
            "can_edit_logistics": can_logistics and row.history_status == "Verified",
        })
    if result:
        item_names = tuple(sorted({row["sales_order_item"] for row in result}))
        schedule_names = tuple(sorted({row["name"] for row in result}))
        planned_rows = frappe.db.sql("""
            SELECT sales_order_item, SUM(planned_qty) AS planned_qty
            FROM `tabSO Delivery Schedule`
            WHERE sales_order_item IN %(item_names)s
            GROUP BY sales_order_item
        """, {"item_names": item_names}, as_dict=True)
        planned_by_item = {row.sales_order_item: flt(row.planned_qty) for row in planned_rows}
        active_dn_rows = frappe.db.sql("""
            SELECT dni.custom_so_delivery_schedule AS schedule, dn.name AS delivery_note,
                dn.workflow_state, dn.docstatus, dn.custom_dr_number, dn.modified AS dn_modified,
                dni.name AS dn_detail, dni.qty,
                EXISTS(SELECT 1 FROM `tabSales Invoice Item` sii
                    JOIN `tabSales Invoice` si ON si.name = sii.parent
                    WHERE sii.dn_detail = dni.name AND si.docstatus < 2) AS has_invoice
            FROM `tabDelivery Note Item` dni JOIN `tabDelivery Note` dn ON dn.name = dni.parent
            WHERE dni.custom_so_delivery_schedule IN %(schedule_names)s AND dn.docstatus IN (0, 1)
            ORDER BY dni.custom_so_delivery_schedule, dn.creation
        """, {"schedule_names": schedule_names}, as_dict=True)
        active_by_schedule = {}
        for active in active_dn_rows:
            active_by_schedule.setdefault(active.schedule, []).append(active)
        draft_allocated_by_schedule = {}
        for active in active_dn_rows:
            if int(active.docstatus) == 0:
                draft_allocated_by_schedule[active.schedule] = (
                    draft_allocated_by_schedule.get(active.schedule, 0) + flt(active.qty)
                )
        history_rows = frappe.get_all("Delivery Note Item", filters={"custom_so_delivery_schedule": ["in", schedule_names]}, pluck="custom_so_delivery_schedule")
        history_schedules = set(history_rows)
        cancelled_history_rows = frappe.db.sql("""
            SELECT dni.custom_so_delivery_schedule AS schedule,
                COUNT(DISTINCT dn.name) AS cancelled_dn_count, SUM(dni.qty) AS cancelled_dn_qty
            FROM `tabDelivery Note Item` dni
            JOIN `tabDelivery Note` dn ON dn.name = dni.parent
            WHERE dni.custom_so_delivery_schedule IN %(schedule_names)s AND dn.docstatus = 2
            GROUP BY dni.custom_so_delivery_schedule
        """, {"schedule_names": schedule_names}, as_dict=True)
        cancelled_by_schedule = {entry.schedule: entry for entry in cancelled_history_rows}
        fulfillment_rows = frappe.db.sql("""
            SELECT dni.custom_so_delivery_schedule AS schedule,
                SUM(CASE WHEN dn.docstatus = 0 THEN dni.qty ELSE 0 END) AS draft_dn_qty,
                SUM(CASE WHEN dn.docstatus = 1 THEN dni.qty ELSE 0 END) AS submitted_dn_qty,
                SUM(CASE WHEN dn.docstatus = 2 THEN dni.qty ELSE 0 END) AS cancelled_dn_qty,
                COUNT(DISTINCT CASE WHEN dn.docstatus = 1 THEN dn.name END) AS submitted_dn_count,
                MAX(CASE WHEN dn.docstatus = 1 THEN dn.posting_date ELSE NULL END) AS last_submitted_delivery_date
            FROM `tabDelivery Note Item` dni
            JOIN `tabDelivery Note` dn ON dn.name = dni.parent
            WHERE dni.custom_so_delivery_schedule IN %(schedule_names)s
            GROUP BY dni.custom_so_delivery_schedule
        """, {"schedule_names": schedule_names}, as_dict=True)
        fulfillment_by_schedule = {entry.schedule: entry for entry in fulfillment_rows}
        from qcmc_logic.api.delivery_schedule_service import _schedule_promise_attributions
        bins = frappe.db.sql("""
            SELECT item_code, warehouse, actual_qty FROM `tabBin`
            WHERE item_code IN %(items)s AND warehouse IN %(warehouses)s
        """, {"items": tuple(sorted({row["item_code"] for row in result})),
            "warehouses": tuple(sorted({row["warehouse"] for row in result}))}, as_dict=True)
        stock_by_pair = {(row.item_code, row.warehouse): flt(row.actual_qty) for row in bins}
        so_cache = {}
        for row in result:
            if row["sales_order"] not in so_cache:
                so_cache[row["sales_order"]] = frappe.get_cached_doc("Sales Order", row["sales_order"])
            so = so_cache[row["sales_order"]]
            row["sales_order_modified"] = str(so.modified)
            row["item_planned_qty"] = planned_by_item.get(row["sales_order_item"], 0)
            active = active_by_schedule.get(row["name"], [])
            row["has_active_dn"] = bool(active)
            row["has_dn_history"] = row["name"] in history_schedules
            row["has_protected_dn"] = row["name"] in cancelled_by_schedule or any(
                int(note.docstatus) == 1 or bool(note.custom_dr_number) or bool(note.has_invoice)
                or note.workflow_state not in (None, "", "Draft", "For Stock Confirmation")
                for note in active
            )
            cancelled = cancelled_by_schedule.get(row["name"])
            row["cancelled_dn_count"] = int(cancelled.cancelled_dn_count) if cancelled else 0
            row["cancelled_dn_qty"] = flt(cancelled.cancelled_dn_qty) if cancelled else 0
            row["active_dn_count"] = len(active)
            row["draft_dn_names"] = sorted({note.delivery_note for note in active if int(note.docstatus) == 0})
            row["draft_allocated_qty"] = draft_allocated_by_schedule.get(row["name"], 0)
            fulfillment = fulfillment_by_schedule.get(row["name"])
            _apply_fulfillment_read_model(row, fulfillment)
            row["promise_commitments"] = [
                {"promise_commitment": commitment, "promise_date": promise_date, "remaining_promise_qty": float(qty)}
                for (commitment, promise_date), qty in _schedule_promise_attributions(row["name"]).items()
            ]
            if len(active) == 1:
                row["active_dn"] = active[0].delivery_note
                row["active_dn_detail"] = active[0].dn_detail
                row["active_dn_state"] = active[0].workflow_state
                row["active_dn_qty"] = flt(active[0].qty)
                row["active_dn_has_dr_number"] = bool(active[0].custom_dr_number)
                row["active_dn_has_invoice"] = bool(active[0].has_invoice)
                row["active_dn_modified"] = str(active[0].dn_modified)
            row["actual_qty"] = stock_by_pair.get((row["item_code"], row["warehouse"]), 0)
    draft_names = sorted({name for row in result if str(row.get("delivery_date")) == str(delivery_date)
        for name in row.get("draft_dn_names", [])})
    pending = [row for row in result if not row.get("has_active_dn") and (
        row.get("history_status") != "Verified" or flt(row.get("current_total")) > 0)]
    pending.extend(_unscheduled_item_rows(company, delivery_date, warehouse, include_overdue, limit))
    return {"rows": pending, "count": len(pending), "draft_dn_count": len(draft_names),
        "possibly_truncated": len(records) == limit}


def _apply_fulfillment_read_model(row, fulfillment):
	"""Keep Draft reservations separate from actual submitted fulfillment in reports."""
	row["draft_dn_qty"] = flt(fulfillment.draft_dn_qty) if fulfillment else 0
	row["submitted_dn_qty"] = flt(fulfillment.submitted_dn_qty) if fulfillment else 0
	row["submitted_dn_count"] = int(fulfillment.submitted_dn_count) if fulfillment else 0
	row["cancelled_dn_qty"] = flt(fulfillment.cancelled_dn_qty) if fulfillment else row.get("cancelled_dn_qty", 0)
	row["last_submitted_delivery_date"] = str(fulfillment.last_submitted_delivery_date) if fulfillment and fulfillment.last_submitted_delivery_date else None
	row["original_promise_commitment"] = row["name"] if flt(row.get("original_qty")) > 0 else None
	# Draft allocations are reservations only; actual fulfillment comes from submitted DNs.
	row["actual_delivered_qty"] = row["submitted_dn_qty"]
	return row


def _unscheduled_item_rows(company, delivery_date, warehouse, include_overdue, limit):
    from qcmc_logic.api.delivery_schedule_service import quantity_state
    operator = "<=" if str(include_overdue) in ("1", "True", "true") else "="
    candidates = frappe.db.sql("""
        SELECT i.name, i.parent FROM `tabSales Order Item` i
        JOIN `tabSales Order` so ON so.name = i.parent
        WHERE so.company = %(company)s AND so.docstatus = 1 AND so.custom_so_type = 'REGULAR'
        AND so.status IN ('To Deliver and Bill', 'To Deliver', 'To Bill')
        AND i.delivery_date """ + operator + """ %(date)s
        AND (%(warehouse)s = '' OR i.warehouse = %(warehouse)s)
        AND NOT EXISTS (SELECT 1 FROM `tabSO Delivery Schedule` s WHERE s.sales_order_item = i.name)
        ORDER BY i.delivery_date, i.name LIMIT %(limit)s
    """, dict(company=company, date=delivery_date, warehouse=warehouse or "", limit=limit), as_dict=True)
    result = []
    for candidate in candidates:
        so = frappe.get_doc("Sales Order", candidate.parent)
        if not frappe.has_permission("Sales Order", "read", doc=so):
            continue
        item = next(i for i in so.items if i.name == candidate.name)
        if not item.warehouse or frappe.db.get_value("Warehouse", item.warehouse, "company") != company:
            continue
        if frappe.db.get_value("Warehouse", item.warehouse, "custom_is_province"):
            continue
        access = {}
        for department, role in (("Sales", _SALES_ROLE), ("Logistics", _LOGISTICS_ROLE)):
            access[department] = False
            if _has_role(role):
                try:
                    _validate_scope(so, item, department, transact=False)
                    access[department] = True
                except frappe.PermissionError:
                    pass
        if not any(access.values()):
            continue
        state = quantity_state(item.name, check_sales_access=False)
        qty = float(max(Decimal(0), state["available_to_schedule_qty"] - state["draft_allocated_qty"]))
        if qty <= 0:
            continue
        result.append(dict(name="unscheduled:" + item.name, sales_order=so.name,
            sales_order_item=item.name, item_code=item.item_code, item_name=item.item_name,
            customer=so.customer, customer_name=so.customer_name, warehouse=item.warehouse,
            delivery_date=str(item.delivery_date), original_qty=qty, planned_qty=qty, current_total=qty,
            quantity_changes=0, history_status="Verified", modified=str(so.modified), uom=item.uom,
            can_edit_sales=access["Sales"], can_edit_logistics=access["Logistics"],
            confirmation_status="Pending", has_active_dn=False, draft_allocated_qty=0))
    return result


def _initialize_unscheduled_item(item_name, expected_modified):
    from qcmc_logic.api.delivery_schedule_service import _load_so_item, quantity_state
    from qcmc_logic.api.sales_order_delivery_eligibility import is_open_sales_order_for_delivery
    _require_role("Logistics")
    so, item = _load_so_item(item_name, lock=True, check_sales_access=False)
    so.check_permission("read")
    if not frappe.has_permission("Company", "read", so.company):
        frappe.throw(_("Company read access is required."), frappe.PermissionError)
    _validate_scope(so, item, "Logistics", transact=True)
    if not is_open_sales_order_for_delivery(so) or so.custom_so_type != "REGULAR":
        frappe.throw(_("Only approved open Regular Sales Orders can be scheduled."))
    if (str(so.modified) != str(expected_modified)
        or frappe.db.exists("SO Delivery Schedule", {"sales_order_item": item_name})):
        frappe.throw(_("Schedule changed. Refresh before trying again."), frappe.TimestampMismatchError)
    if (not item.delivery_date or not item.warehouse
        or frappe.db.get_value("Warehouse", item.warehouse, "company") != so.company
        or frappe.db.get_value("Warehouse", item.warehouse, "custom_is_province")):
        frappe.throw(_("A valid item delivery date and non-provincial warehouse are required."))
    state = quantity_state(item.name, lock=True, check_sales_access=False)
    available = state["available_to_schedule_qty"] - state["draft_allocated_qty"]
    if available <= 0:
        frappe.throw(_("No unscheduled quantity remains."), frappe.TimestampMismatchError)
    previous = frappe.flags.get("delivery_schedule_service_write")
    frappe.flags.delivery_schedule_service_write = True
    try:
        row = frappe.get_doc(dict(doctype="SO Delivery Schedule", sales_order=so.name,
            sales_order_item=item.name, item_code=item.item_code, warehouse=item.warehouse,
            delivery_date=item.delivery_date, planned_qty=float(available),
            uom=item.uom, conversion_factor=item.conversion_factor,
            remarks=_("Original Sales commitment from Sales Order Item delivery date."))).insert(ignore_permissions=True)
    finally:
        frappe.flags.delivery_schedule_service_write = previous
    return row.name, str(row.modified)
