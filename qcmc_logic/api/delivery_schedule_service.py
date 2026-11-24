"""Transactional operational delivery planning; SO Item rows remain commercial authority."""

from decimal import Decimal, InvalidOperation
import hashlib

import frappe
from frappe import _
from frappe.utils import flt, getdate

DN_SCHEDULE_FIELD = "custom_so_delivery_schedule"
SCHEDULE_ORIGINAL_FIELDS = ("original_delivery_date", "original_qty", "original_promise_date",
	"original_promise_qty", "source_schedule", "source_date", "movement_transaction_id")


def calculate_schedule_quantities(original_qty, changes, submitted_qty, active_allocated_qty, precision):
	"""Pure accounting equation: fulfillment and reservations never change committed Total."""
	quantum = Decimal(1).scaleb(-precision)
	values = [Decimal(str(value or 0)) for value in
		(original_qty, changes, submitted_qty, active_allocated_qty)]
	original, net_changes, submitted, active = values
	total = original + net_changes
	available = total - submitted - active
	if any(not value.is_finite() for value in values) or total < 0 or submitted < 0 or active < 0 or available < 0:
		frappe.throw(_("Schedule quantities are inconsistent or over-allocated."))
	if any(value.quantize(quantum) != value for value in values) or total.quantize(quantum) != total:
		frappe.throw(_("Schedule quantities exceed the item's allowed precision."))
	return {"original_qty": original, "changes": net_changes, "total": total,
		"submitted_qty": submitted, "active_allocated_qty": active, "available_for_new_dr": available}


def calculate_so_schedule_balance(ordered_qty, scheduled_total, submitted_qty,
		submitted_linked_to_schedules, precision):
	"""Keep linked fulfillment inside its schedule; only unlinked fulfillment consumes unscheduled demand."""
	quantum = Decimal(1).scaleb(-precision)
	ordered, scheduled, submitted, linked = (Decimal(str(value or 0)) for value in
		(ordered_qty, scheduled_total, submitted_qty, submitted_linked_to_schedules))
	if any(not value.is_finite() or value < 0 or value.quantize(quantum) != value
		for value in (ordered, scheduled, submitted, linked)) or linked > submitted:
		frappe.throw(_("Sales Order fulfillment quantities are inconsistent."))
	unlinked_fulfillment = submitted - linked
	if scheduled + unlinked_fulfillment > ordered:
		frappe.throw(_("Schedules and unlinked fulfillment exceed the Sales Order Item quantity."))
	return {"unlinked_fulfillment_qty": unlinked_fulfillment,
		"unscheduled_qty": ordered - scheduled - unlinked_fulfillment}


def validate_schedule_allocation(total, submitted_qty, other_draft_qty, current_dn_qty, precision):
	"""Central DN reservation check. The current document is excluded from persisted drafts."""
	state = calculate_schedule_quantities(total, 0, submitted_qty,
		Decimal(str(other_draft_qty or 0)) + Decimal(str(current_dn_qty or 0)), precision)
	return state


def append_schedule_movement(*, operation_type, sales_order, sales_order_item, quantity, uom,
		promise_date, promise_qty, reason, promise_commitment=None, source_schedule=None, destination_schedule=None,
		source_before=None, source_after=None, destination_before=None, destination_after=None,
		related_delivery_note=None, related_dn_item=None, idempotency_key=None, transaction_id=None):
	"""Append immutable movement evidence within the caller's database transaction."""
	key = idempotency_key or hashlib.sha256(f"{operation_type}|{source_schedule}|{destination_schedule}|{frappe.generate_hash(length=20)}".encode()).hexdigest()
	existing = frappe.db.get_value("Delivery Schedule Movement", {"idempotency_key": key}, "name")
	if existing:
		return frappe.get_doc("Delivery Schedule Movement", existing)
	previous = frappe.flags.get("delivery_schedule_movement_service_write")
	frappe.flags.delivery_schedule_movement_service_write = True
	try:
		movement = frappe.get_doc({"doctype": "Delivery Schedule Movement", "operation_type": operation_type,
			"sales_order": sales_order, "sales_order_item": sales_order_item, "quantity": float(quantity),
			"uom": uom, "promise_date": promise_date, "promise_qty": float(promise_qty),
			"promise_commitment": promise_commitment,
			"reason": reason, "authorized_by": frappe.session.user, "authorized_at": frappe.utils.now_datetime(),
			"source_schedule": source_schedule, "destination_schedule": destination_schedule,
			"source_before": source_before, "source_after": source_after,
			"destination_before": destination_before, "destination_after": destination_after,
			"related_delivery_note": related_delivery_note, "related_dn_item": related_dn_item,
			"transaction_id": transaction_id, "idempotency_key": key})
		movement.insert(ignore_permissions=True)
		return movement
	finally:
		frappe.flags.delivery_schedule_movement_service_write = previous


def _schedule_promise_attributions(schedule_name):
	"""Rebuild promise-origin balances from append-only initial/transfer movements."""
	rows = frappe.get_all("Delivery Schedule Movement",
		filters={"operation_type": ["in", ["Initial Commitment", "Transfer In", "Transfer Out",
			"Sales Finalization Split In", "Sales Finalization Split Out", "Quantity Adjustment"]]},
		fields=["operation_type", "source_schedule", "destination_schedule", "promise_date", "promise_qty", "promise_commitment"],
		or_filters={"source_schedule": schedule_name, "destination_schedule": schedule_name},
		order_by="promise_date asc, creation asc, name asc")
	balances = {}
	for row in rows:
		commitment = row.promise_commitment or (row.destination_schedule if row.operation_type == "Initial Commitment"
			else f"legacy:{row.promise_date}")
		key = (commitment, row.promise_date)
		if row.operation_type in ("Initial Commitment", "Transfer In", "Sales Finalization Split In") and row.destination_schedule == schedule_name:
			balances[key] = balances.get(key, Decimal(0)) + Decimal(str(row.promise_qty or 0))
		elif row.operation_type in ("Transfer Out", "Sales Finalization Split Out") and row.source_schedule == schedule_name:
			balances[key] = balances.get(key, Decimal(0)) - Decimal(str(row.promise_qty or 0))
		elif row.operation_type == "Quantity Adjustment":
			if row.destination_schedule == schedule_name:
				balances[key] = balances.get(key, Decimal(0)) + Decimal(str(row.promise_qty or 0))
			elif row.source_schedule == schedule_name:
				balances[key] = balances.get(key, Decimal(0)) - Decimal(str(row.promise_qty or 0))
	ordered = sorted(balances.items(), key=lambda entry: (entry[0][1], entry[0][0]))
	return {(commitment, promise_date): qty for (commitment, promise_date), qty in ordered if qty > 0}


def _allocate_promise_attributions(schedule_name, quantity, fallback_date=None):
	remaining = Decimal(str(quantity))
	balances = _schedule_promise_attributions(schedule_name)
	result = []
	for (commitment, promise_date), available in balances.items():
		amount = min(remaining, available)
		if amount > 0:
			result.append((commitment, promise_date, amount))
			remaining -= amount
		if remaining == 0:
			break
	if remaining > 0:
		frappe.throw(_("Schedule {0} has insufficient verified promise attribution for this transfer.").format(schedule_name))
	return result


def _decimal(value, precision):
	try:
		amount = Decimal(str(value))
	except (InvalidOperation, TypeError, ValueError):
		frappe.throw(_("Enter a valid quantity."))
	quantum = Decimal(1).scaleb(-precision)
	if not amount.is_finite() or amount <= 0 or amount.quantize(quantum) != amount:
		frappe.throw(_("Quantity must be positive and use the item's allowed precision."))
	return amount


def _snapshot_decimal(value):
	try:
		amount = Decimal(str(value))
	except (InvalidOperation, TypeError, ValueError):
		frappe.throw(_("Refresh the schedule before applying changes."), frappe.TimestampMismatchError)
	if not amount.is_finite() or amount < 0:
		frappe.throw(_("Refresh the schedule before applying changes."), frappe.TimestampMismatchError)
	return amount


def _require_sales_access(so, item=None, require_transact=False):
	if "Sales Coordinator" not in frappe.get_roles():
		frappe.throw(_("Sales Coordinator access is required."), frappe.PermissionError)
	so.check_permission("read")
	if not frappe.has_permission("Company", "read", so.company):
		frappe.throw(_("You cannot schedule deliveries for company {0}.").format(so.company), frappe.PermissionError)
	if item and require_transact:
		from qcmc_logic.api.sales_order_scheduling_service import _validate_sales_coordinator_access
		_validate_sales_coordinator_access(so, item, require_transact=True)
		if frappe.db.get_value("Warehouse", item.warehouse, "company") != so.company:
			frappe.throw(_("The item's warehouse must belong to the Sales Order company."))


def _load_so_item(so_item, lock=False, allow_draft=False, check_sales_access=True):
	parent = frappe.db.get_value("Sales Order Item", so_item, "parent")
	if not parent:
		frappe.throw(_("Sales Order Item was not found."))
	if lock:
		frappe.db.sql("SELECT name FROM `tabSales Order` WHERE name = %s FOR UPDATE", parent)
	so = frappe.get_doc("Sales Order", parent)
	row = next((item for item in so.items if item.name == so_item), None)
	if not row or so.docstatus != 1 and not (allow_draft and so.docstatus == 0) or so.get("is_return"):
		frappe.throw(_("Schedules require an item on an active Sales Order."))
	if check_sales_access:
		_require_sales_access(so)
	return so, row


def _lock_schedules(so_item):
	names = frappe.get_all("SO Delivery Schedule", filters={"sales_order_item": so_item}, pluck="name", order_by="name asc")
	if names:
		frappe.db.sql("SELECT name FROM `tabSO Delivery Schedule` WHERE name IN %(names)s ORDER BY name FOR UPDATE", {"names": tuple(sorted(names))})
	return names


def _clear_schedule_confirmation(schedule):
	"""Any change to the operational plan requires both departments to review it again."""
	for fieldname in ("sales_proposed_qty", "sales_remarks", "logistics_committed_qty", "logistics_remarks",
		"final_qty", "sales_confirmed_by", "logistics_confirmed_by", "finalized_at"):
		if schedule.meta.has_field(fieldname):
			schedule.set(fieldname, None)
	if schedule.meta.has_field("confirmation_status"):
		schedule.confirmation_status = "Pending"


def _assert_schedule_plan_editable(schedule):
	if schedule.get("confirmation_status") == "Finalized":
		frappe.throw(_("Reopen the finalized schedule before changing its plan."))
	if schedule.get("logistics_confirmed_by"):
		frappe.throw(_("Logistics owns changes to a confirmed commitment. Submit an authorized Logistics correction."))
	if frappe.db.exists("Delivery Note Item", {DN_SCHEDULE_FIELD: schedule.name}):
		frappe.throw(_("A schedule linked to a Delivery Note cannot be changed."))


def quantity_state(so_item, lock=False, check_sales_access=True):
	"""Return demand, plan, draft allocations and derived unscheduled balance."""
	so, item = _load_so_item(so_item, lock=lock, check_sales_access=check_sales_access)
	if lock:
		_lock_schedules(item.name)
	precision = item.precision("qty")
	ordered = Decimal(str(flt(item.qty, precision)))
	delivered = Decimal(str(flt(item.delivered_qty, precision)))
	remaining = max(Decimal(0), ordered - delivered)
	rows = frappe.get_all("SO Delivery Schedule", filters={"sales_order_item": item.name},
		fields=["name", "planned_qty", "current_total", "original_qty", "quantity_changes",
		"history_status", "delivery_date", "original_delivery_date", "warehouse", "modified"], order_by="name asc")
	totals = {row.name: Decimal(str(flt(
		row.current_total if row.history_status == "Verified" else row.planned_qty, precision))) for row in rows}
	dn_rows = frappe.db.sql("""
		SELECT dni.custom_so_delivery_schedule AS schedule, dn.docstatus, SUM(dni.qty) AS qty
		FROM `tabDelivery Note Item` dni JOIN `tabDelivery Note` dn ON dn.name = dni.parent
		WHERE dni.custom_so_delivery_schedule IN %(names)s AND dn.docstatus IN (0, 1)
		GROUP BY dni.custom_so_delivery_schedule, dn.docstatus
	""", {"names": tuple(row.name for row in rows)}, as_dict=True) if rows else []
	submitted_by_schedule = {row.name: Decimal(0) for row in rows}
	draft_by_schedule = {row.name: Decimal(0) for row in rows}
	for allocation in dn_rows:
		qty = Decimal(str(flt(allocation.qty, precision)))
		if int(allocation.docstatus) == 1:
			submitted_by_schedule[allocation.schedule] += qty
		elif int(allocation.docstatus) == 0:
			draft_by_schedule[allocation.schedule] += qty
	for schedule in rows:
		allocation = draft_by_schedule.get(schedule.name, Decimal(0))
		try:
			calculate_schedule_quantities(totals[schedule.name], 0, submitted_by_schedule[schedule.name], allocation, precision)
		except frappe.ValidationError:
			frappe.throw(_("Submitted and draft Delivery Note allocations exceed schedule {0} Total.").format(schedule.name))
	planned = sum(totals.values(), Decimal(0))
	fulfillment = frappe.db.sql("""
		SELECT COALESCE(SUM(dni.qty), 0) AS submitted_qty,
			COALESCE(SUM(CASE WHEN dni.custom_so_delivery_schedule IS NOT NULL AND dni.custom_so_delivery_schedule != ''
				THEN dni.qty ELSE 0 END), 0) AS linked_qty
		FROM `tabDelivery Note Item` dni JOIN `tabDelivery Note` dn ON dn.name = dni.parent
		WHERE dni.against_sales_order = %s AND dni.so_detail = %s AND dn.docstatus = 1 AND IFNULL(dn.is_return, 0) = 0
	""", (so.name, item.name), as_dict=True)[0]
	so_balance = calculate_so_schedule_balance(ordered, planned,
		fulfillment.submitted_qty or 0, fulfillment.linked_qty or 0, precision)
	unscheduled = so_balance["unscheduled_qty"]
	return {
		"sales_order": so.name, "sales_order_item": item.name,
		"ordered_qty": ordered, "delivered_qty": delivered, "remaining_qty": remaining,
		"planned_qty": planned, "draft_allocated_qty": sum(draft_by_schedule.values(), Decimal(0)),
		"unlinked_fulfillment_qty": so_balance["unlinked_fulfillment_qty"],
		"draft_allocated_by_schedule": draft_by_schedule,
		"available_to_schedule_qty": unscheduled,
		"submitted_by_schedule": submitted_by_schedule,
		"available_scheduled_qty": {row.name: totals[row.name] - submitted_by_schedule[row.name] - draft_by_schedule[row.name] for row in rows},
		"schedules": rows, "precision": precision,
	}


def derived_unplanned_qty(ordered_qty, delivered_qty, scheduled_total, submitted_linked_qty=0):
	"""Return unscheduled demand without subtracting schedule-linked delivery twice."""
	state = calculate_so_schedule_balance(ordered_qty, scheduled_total, delivered_qty,
		submitted_linked_qty, 6)
	return state["unscheduled_qty"]


def validate_schedule_document(doc):
	so = frappe.get_doc("Sales Order", doc.sales_order)
	so.check_permission("read")
	item = next((row for row in so.items if row.name == doc.sales_order_item), None)
	if so.docstatus not in (0, 1) or not item or so.get("is_return"):
		frappe.throw(_("Schedule must reference an active Sales Order Item."))
	if item.item_code != doc.item_code or item.warehouse != doc.warehouse:
		frappe.throw(_("Schedule item and warehouse must match the Sales Order Item."))
	if frappe.db.get_value("Warehouse", doc.warehouse, "company") != so.company:
		frappe.throw(_("Schedule warehouse must belong to the Sales Order company."))
	if item.uom != doc.uom or flt(item.conversion_factor) != flt(doc.conversion_factor):
		frappe.throw(_("Schedule UOM and conversion factor must match the Sales Order Item."))
	if not doc.delivery_date or getdate(doc.delivery_date) < getdate(so.transaction_date):
		frappe.throw(_("Schedule date must be on or after the Sales Order transaction date."))
	if not doc.remarks or not doc.remarks.strip():
		frappe.throw(_("Enter a reason for the schedule change."))
	if doc.is_new():
		if not frappe.flags.get("delivery_schedule_service_write"):
			frappe.throw(_("Create schedules through the delivery schedule service."), frappe.PermissionError)
		transfer = frappe.flags.get("delivery_schedule_transfer_context") or {}
		initial_qty = Decimal(str(doc.planned_qty or 0))
		valid_totals = (Decimal(str(doc.original_qty or 0)) + Decimal(str(doc.quantity_changes or 0))
			== Decimal(str(doc.current_total or 0)) == initial_qty)
		valid_origin = (Decimal(str(doc.original_qty or 0)) == 0 and Decimal(str(doc.original_promise_qty or 0)) == 0
			if transfer else Decimal(str(doc.original_qty or 0)) == initial_qty)
		valid_provenance = (bool(doc.source_schedule and doc.source_date and doc.movement_transaction_id)
			if transfer else not doc.source_schedule and not doc.source_date and not doc.movement_transaction_id)
		if (not doc.original_delivery_date or doc.original_delivery_date != doc.delivery_date
			or not valid_totals or not valid_origin or not valid_provenance):
			frappe.throw(_("New schedule original values must match its initial date and quantity."))
	elif not frappe.flags.get("delivery_schedule_controlled_reconciliation"):
		_validate_original_schedule_fields_unchanged(doc)
	if doc.get("history_status") != "Verified" and not doc.is_new():
		if doc.get("confirmation_status") == "Finalized" or doc.get("final_qty"):
			frappe.throw(_("Reconcile this historical schedule before finalizing or allocating it."))
	qty = Decimal(str(doc.planned_qty or 0))
	quantum = Decimal(1).scaleb(-item.precision("qty"))
	if not qty.is_finite() or qty < 0 or qty.quantize(quantum) != qty or (doc.is_new() and qty <= 0):
		frappe.throw(_("Planned quantity must be non-negative and use the item's allowed precision."))
	if doc.is_new() and not frappe.flags.get("delivery_schedule_service_write"):
		frappe.throw(_("Create schedules through the delivery schedule service."), frappe.PermissionError)
	if not doc.is_new() and not frappe.flags.get("delivery_schedule_service_write"):
		frappe.throw(_("Change schedules through the delivery schedule service."), frappe.PermissionError)
	if doc.get("history_status") == "Verified" and frappe.flags.get("delivery_schedule_service_write"):
		doc.current_total = float(qty)
		doc.quantity_changes = float(qty - Decimal(str(doc.original_qty or 0)))
	if doc.get("history_status") == "Verified":
		expected_total = Decimal(str(doc.original_qty or 0)) + Decimal(str(doc.quantity_changes or 0))
		if expected_total < 0 or Decimal(str(doc.current_total or 0)) != expected_total or Decimal(str(doc.planned_qty or 0)) != expected_total:
			frappe.throw(_("Current Total must equal Original QTY plus net Changes."))


@frappe.whitelist(methods=["POST"])
def create_schedule(so_item, delivery_date, qty, remarks, expected_so_modified, expected_planned_qty):
	"""Move derived unscheduled demand into a new dated schedule; stale retry is rejected."""
	so, item = _load_so_item(so_item, lock=True)
	_require_sales_access(so, item, require_transact=True)
	if str(so.modified) != str(expected_so_modified):
		frappe.throw(_("Sales Order changed. Refresh the schedule before applying."), frappe.TimestampMismatchError)
	state = quantity_state(item.name, lock=True)
	if _snapshot_decimal(expected_planned_qty) != state["planned_qty"]:
		frappe.throw(_("Sales Order schedule allocations changed. Refresh before applying."), frappe.TimestampMismatchError)
	amount = _decimal(qty, state["precision"])
	if amount > state["available_to_schedule_qty"]:
		frappe.throw(_("Requested quantity exceeds unscheduled SO demand."))
	if not delivery_date or getdate(delivery_date) < getdate(so.transaction_date):
		frappe.throw(_("Choose a valid delivery date."))
	if not isinstance(remarks, str) or not remarks.strip():
		frappe.throw(_("Enter a reason for the schedule change."))
	# Keep each Sales scheduling act as its own baseline record, even when
	# another commitment for this SO Item already has the same delivery date.
	doc = frappe.get_doc({"doctype": "SO Delivery Schedule", "sales_order": so.name,
		"sales_order_item": item.name, "item_code": item.item_code,
		"warehouse": item.warehouse, "delivery_date": delivery_date,
		"planned_qty": float(amount), "uom": item.uom,
		"conversion_factor": item.conversion_factor, "remarks": remarks.strip()})
	frappe.flags.delivery_schedule_service_write = True
	try:
		doc.insert(ignore_permissions=True)
	finally:
		frappe.flags.delivery_schedule_service_write = False
	return {"schedule": doc.name, "state": quantity_state(item.name)}


def _form_schedule_snapshot(item_name):
	rows = frappe.get_all("SO Delivery Schedule", filters={"sales_order_item": item_name},
		fields=["name", "delivery_date", "planned_qty", "remarks", "modified", "history_status"], order_by="delivery_date asc, name asc")
	allocations = frappe.db.sql("""
		SELECT dni.custom_so_delivery_schedule AS schedule,
			SUM(CASE WHEN dn.docstatus = 0 THEN dni.qty ELSE 0 END) AS draft_qty,
			MAX(CASE WHEN dn.docstatus > 0 THEN 1 ELSE 0 END) AS locked_date,
			COUNT(dni.name) AS has_history
		FROM `tabDelivery Note Item` dni JOIN `tabDelivery Note` dn ON dn.name = dni.parent
		WHERE dni.custom_so_delivery_schedule IN %(names)s
		GROUP BY dni.custom_so_delivery_schedule
	""", {"names": tuple(row.name for row in rows)}, as_dict=True) if rows else []
	by_schedule = {row.schedule: row for row in allocations}
	return {"rows": rows,
		"allocated": {row.name: flt(by_schedule[row.name].draft_qty) for row in rows if row.name in by_schedule},
		"locked_date": {row.name: bool(by_schedule[row.name].locked_date) for row in rows if row.name in by_schedule},
		"has_history": {row.name: bool(by_schedule[row.name].has_history) for row in rows if row.name in by_schedule}}


def _build_form_schedule_operations(clean, snapshot):
	"""Translate form edits into adjustments or source-linked transfers; never rewrite baselines."""
	clean_by_name = {entry["name"]: entry for entry in clean if entry.get("name")}
	operations, new_entries, kept = [], [], set()
	for row in snapshot["rows"]:
		entry = clean_by_name.get(row.name)
		if getdate(row.delivery_date) < getdate():
			if not entry or (str(entry["delivery_date"]) != str(row.delivery_date)
				or Decimal(str(entry["planned_qty"])) != Decimal(str(row.planned_qty))
				or (entry.get("remarks") or "").strip() != (row.remarks or "").strip()):
				frappe.throw(_("Past schedules must be moved through Delivery Schedule Workbench."))
			kept.add(row.name)
			continue
		if row.get("history_status") != "Verified":
			if not entry or (str(entry["delivery_date"]) != str(row.delivery_date)
				or Decimal(str(entry["planned_qty"])) != Decimal(str(row.planned_qty))
				or (entry.get("remarks") or "").strip() != (row.remarks or "").strip()):
				frappe.throw(_("Schedule {0} has unreconciled history. Preserve it and complete reconciliation before editing this item.").format(row.name))
			kept.add(row.name)
			continue
		allocated = Decimal(str(snapshot["allocated"].get(row.name, 0)))
		has_history = snapshot["has_history"].get(row.name, False)
		date_locked = snapshot["locked_date"].get(row.name, False)
		old_date = str(row.delivery_date)
		current = Decimal(str(row.planned_qty or 0))
		if not entry:
			target = allocated
			if has_history and not allocated:
				frappe.throw(_("A schedule with Delivery Note history cannot be removed from its plan."))
			if target != current:
				operations.append(("adjust", row, old_date, target, row.remarks))
			kept.add(row.name)
			continue
		new_date, qty = str(entry["delivery_date"]), entry["planned_qty"]
		if qty < allocated:
			frappe.throw(_("Planned quantity cannot be less than active draft Delivery Note allocation."))
		if new_date != old_date and date_locked:
			frappe.throw(_("Schedule {0} has submitted or cancelled Delivery Note history; its date is locked." ).format(row.name))
		if new_date != old_date:
			if has_history and not allocated:
				frappe.throw(_("A schedule with Delivery Note history cannot be moved."))
			if qty < current:
				operations.append(("adjust", row, old_date, qty, entry["remarks"]))
			elif qty > current:
				new_entries.append({"date": new_date, "qty": qty - current,
					"remarks": entry["remarks"]})
			move_qty = min(qty, current) - allocated
			if move_qty <= 0:
				frappe.throw(_("Keep the committed quantity on its original date; there is no free quantity to move."))
			operations.append(("transfer", row, new_date, move_qty, entry["remarks"]))
			kept.add(row.name)
		else:
			if has_history and qty != current:
				frappe.throw(_("A schedule with Delivery Note history cannot be quantity-adjusted in the Sales Order form."))
			if qty > current:
				frappe.throw(_("Add a separate schedule row for additional quantity so its Sales commitment remains distinct."))
			if qty != current:
				operations.append(("adjust", row, new_date, qty, entry["remarks"]))
			kept.add(row.name)

	for entry in clean:
		if not entry.get("name"):
			new_entries.append({"date": str(entry["delivery_date"]), "qty": entry["planned_qty"],
				"remarks": entry["remarks"]})
	return operations, new_entries, kept


@frappe.whitelist()
def get_form_schedule_state(sales_order, sales_order_item):
	"""Permission-checked schedule editor data for one original Sales Order Item."""
	so, item = _load_so_item(sales_order_item, allow_draft=True)
	if so.name != sales_order:
		frappe.throw(_("Sales Order Item does not belong to the selected Sales Order."))
	_require_sales_access(so, item, require_transact=True)
	_validate_form_schedule_eligibility(so, item)
	snapshot = _form_schedule_snapshot(item.name)
	return {
		"sales_order": so.name, "sales_order_item": item.name, "sales_order_modified": str(so.modified),
		"docstatus": so.docstatus,
		"ordered_qty": flt(item.qty), "delivered_qty": flt(item.delivered_qty),
		"precision": item.precision("qty"),
		"rows": [{"name": row.name, "delivery_date": str(row.delivery_date),
			"planned_qty": flt(row.planned_qty), "allocated_qty": snapshot["allocated"].get(row.name, 0),
			"editable_qty": max(0, flt(row.planned_qty) - snapshot["allocated"].get(row.name, 0)),
			"has_dn_history": snapshot["has_history"].get(row.name, False),
			"date_locked": snapshot["locked_date"].get(row.name, False),
			"remarks": row.remarks, "history_status": row.history_status,
			"modified": str(row.modified)} for row in snapshot["rows"]],
		"state": hashlib.sha256(frappe.as_json({
			"so_modified": str(so.modified), "item": item.name, "qty": flt(item.qty),
			"delivered": flt(item.delivered_qty), "rows": snapshot["rows"],
			"allocated": snapshot["allocated"], "locked_date": snapshot["locked_date"],
			"has_history": snapshot["has_history"],
		}).encode()).hexdigest(),
	}


def _get_sales_order_schedule_grid(so):
	_require_sales_access(so)
	if so.docstatus not in (0, 1) or so.get("is_return"):
		frappe.throw(_("This Sales Order is not available for delivery scheduling."))
	items, rows, item_states = [], [], {}
	for item in so.items:
		state = get_form_schedule_state(so.name, item.name)
		item_states[item.name] = state["state"]
		item_rows = state["rows"]
		item_plan = sum((Decimal(str(row["planned_qty"])) for row in item_rows), Decimal(0))
		item_committed = sum((Decimal(str(row["allocated_qty"])) for row in item_rows), Decimal(0))
		remaining = max(Decimal(0), Decimal(str(state["ordered_qty"])) - Decimal(str(state["delivered_qty"])))
		item_info = {"sales_order_item": item.name, "idx": item.idx, "item_code": item.item_code,
			"item_name": item.item_name, "uom": item.uom, "ordered_qty": flt(state["ordered_qty"]),
			"delivered_qty": flt(state["delivered_qty"]), "remaining_qty": float(remaining),
			"precision": state["precision"]}
		items.append(item_info)
		for schedule in item_rows:
			rows.append({**item_info, "schedule_name": schedule.get("name"),
				"delivery_date": schedule.get("delivery_date") or "",
				"planned_qty": flt(schedule.get("planned_qty")),
				"dn_committed_qty": flt(schedule.get("allocated_qty")),
				"editable_qty": flt(schedule.get("editable_qty")),
				"total_scheduled_qty": float(item_plan),
				"total_committed_qty": float(item_committed),
				"unscheduled_qty": float(max(Decimal(0), remaining - item_plan)),
				"has_dn_history": bool(schedule.get("has_dn_history")),
				"date_locked": bool(schedule.get("date_locked")),
				"remarks": schedule.get("remarks") or "",
				"history_status": schedule.get("history_status") or "Unreconciled"})
	return {"sales_order": so.name, "docstatus": so.docstatus, "items": items, "rows": rows,
		"item_states": item_states,
		"state": hashlib.sha256(frappe.as_json({"so_modified": str(so.modified),
			"item_states": item_states, "items": [(item.name, flt(item.qty), flt(item.delivered_qty)) for item in so.items]}).encode()).hexdigest()}


@frappe.whitelist()
def get_sales_order_schedule_grid(sales_order):
	"""Return one combined editable schedule grid for every eligible Sales Order Item."""
	return _get_sales_order_schedule_grid(frappe.get_doc("Sales Order", sales_order))


@frappe.whitelist(methods=["POST"])
def save_sales_order_schedule_grid(sales_order, entries, expected_state):
	"""Atomically save every item plan in one Sales Order schedule grid."""
	if isinstance(entries, str):
		entries = frappe.parse_json(entries)
	if not isinstance(entries, list) or len(entries) > 500:
		frappe.throw(_("Provide a valid Sales Order schedule grid."))
	so_name = frappe.db.get_value("Sales Order", sales_order, "name")
	if not so_name:
		frappe.throw(_("Sales Order was not found."))
	frappe.db.sql("SELECT name FROM `tabSales Order` WHERE name = %s FOR UPDATE", so_name)
	so = frappe.get_doc("Sales Order", so_name)
	grid = _get_sales_order_schedule_grid(so)
	if not expected_state or grid["state"] != expected_state:
		frappe.throw(_("Sales Order delivery schedules changed. Refresh before saving."), frappe.TimestampMismatchError)
	by_item = {item.name: [] for item in so.items}
	for entry in entries:
		if not isinstance(entry, dict) or entry.get("sales_order_item") not in by_item:
			frappe.throw(_("Each schedule row must reference an item on this Sales Order."))
		by_item[entry["sales_order_item"]].append({
			"name": entry.get("schedule_name"), "delivery_date": entry.get("delivery_date"),
			"planned_qty": entry.get("planned_qty"), "remarks": entry.get("remarks"),
		})
	for item_name in sorted(by_item):
		_lock_schedules(item_name)
	sp = "save_sales_order_schedule_grid"
	frappe.db.savepoint(sp)
	try:
		for item_name, item_entries in by_item.items():
			save_form_schedule_plan(sales_order, item_name, item_entries,
				grid["item_states"][item_name])
	except Exception:
		frappe.db.rollback(save_point=sp)
		raise
	return _get_sales_order_schedule_grid(frappe.get_doc("Sales Order", sales_order))


@frappe.whitelist(methods=["POST"])
def save_form_schedule_plan(sales_order, sales_order_item, entries, expected_state, remarks=None):
	"""Atomically save a date plan without writing or splitting Sales Order Items."""
	if isinstance(entries, str):
		entries = frappe.parse_json(entries)
	if not isinstance(entries, list) or (remarks is not None and not isinstance(remarks, str)):
		frappe.throw(_("Provide a valid schedule plan."))
	if len(entries) > 50:
		frappe.throw(_("A Sales Order Item can have at most 50 schedule dates."))
	so, item = _load_so_item(sales_order_item, lock=True, allow_draft=True)
	if so.name != sales_order:
		frappe.throw(_("Sales Order Item does not belong to the selected Sales Order."))
	_require_sales_access(so, item, require_transact=True)
	_validate_form_schedule_eligibility(so, item)
	_lock_schedules(item.name)
	so.reload()
	item = next((row for row in so.items if row.name == sales_order_item), None)
	if not item:
		frappe.throw(_("Sales Order Item no longer exists."), frappe.TimestampMismatchError)
	current = get_form_schedule_state(so.name, item.name)
	if not expected_state or current["state"] != expected_state:
		frappe.throw(_("Sales Order or schedule plan changed. Refresh before saving."), frappe.TimestampMismatchError)
	precision = item.precision("qty")
	clean = []
	total = Decimal(0)
	existing_by_name = {row.name: row for row in _form_schedule_snapshot(item.name)["rows"]}
	for entry in entries:
		if not isinstance(entry, dict):
			frappe.throw(_("Each schedule row must have a date and quantity."))
			continue
		date = getdate(entry.get("delivery_date")) if entry.get("delivery_date") else None
		if not date or date < getdate(so.transaction_date):
			frappe.throw(_("Schedule dates must be on or after the Sales Order date."))
		if entry.get("name") and entry["name"] not in existing_by_name:
			frappe.throw(_("A schedule row no longer belongs to this Sales Order Item."), frappe.TimestampMismatchError)
		qty = _schedule_plan_quantity(entry.get("planned_qty"), precision)
		total += qty
		existing_row = existing_by_name.get(entry.get("name")) if entry.get("name") else None
		entry_remarks = entry.get("remarks") or remarks or (existing_row.remarks if existing_row else "")
		if not isinstance(entry_remarks, str) or (qty > 0 and not entry_remarks.strip()):
			frappe.throw(_("Enter Reason / Remarks for each scheduled row."))
		clean.append({"name": entry.get("name"), "delivery_date": date,
			"planned_qty": qty, "remarks": entry_remarks.strip()})
	remaining = Decimal(str(flt(item.qty - item.delivered_qty, precision)))
	if total > remaining:
		frappe.throw(_("Planned schedule quantity cannot exceed the Sales Order Item's remaining quantity."))
	snapshot = _form_schedule_snapshot(item.name)
	if sum(Decimal(str(row.planned_qty)) for row in snapshot["rows"]) >= remaining:
		old_names = {row.name for row in snapshot["rows"]}
		new_names = {entry["name"] for entry in clean if entry.get("name")}
		if old_names != new_names or any(not entry.get("name") for entry in clean):
			frappe.throw(_("This item is fully scheduled. Adjust an eligible future row before adding or removing schedule rows."))
	operations, new_by_date, kept = _build_form_schedule_operations(clean, snapshot)

	submitted_schedule_names = {entry["name"] for entry in clean if entry.get("name")}
	final_total = total + sum((Decimal(str(snapshot["allocated"].get(row.name, 0)))
		for row in snapshot["rows"] if row.name not in submitted_schedule_names), Decimal(0))
	if final_total > Decimal(str(flt(item.qty - item.delivered_qty, precision))):
		frappe.throw(_("Scheduled quantity cannot exceed the Sales Order Item's remaining quantity."))
	sp = "save_form_delivery_schedule_plan"
	frappe.db.savepoint(sp)
	previous_service_write = frappe.flags.get("delivery_schedule_service_write")
	try:
		for action, row, delivery_date, qty, row_remarks in operations:
			if action == "adjust":
				doc = frappe.get_doc("SO Delivery Schedule", row.name, for_update=True)
				_adjust_schedule_total(doc, qty, row_remarks or remarks or _("Sales Order schedule adjustment"),
					idempotency_key=f"so-form-adjust:{row.name}:{current['state']}:{qty}")
			elif action == "transfer":
				doc = frappe.get_doc("SO Delivery Schedule", row.name, for_update=True)
				_transfer_to_new_schedule(doc, so, item, qty, delivery_date, row_remarks,
					idempotency_key=f"so-form-transfer:{row.name}:{current['state']}:{delivery_date}:{qty}")
		for values in new_by_date:
			doc = frappe.get_doc({"doctype": "SO Delivery Schedule", "sales_order": so.name,
				"sales_order_item": item.name, "item_code": item.item_code,
				"warehouse": item.warehouse, "delivery_date": values["date"],
				"planned_qty": float(values["qty"]), "uom": item.uom,
				"conversion_factor": item.conversion_factor, "remarks": values["remarks"]})
			frappe.flags.delivery_schedule_service_write = True
			doc.insert(ignore_permissions=True)
	except Exception:
		frappe.db.rollback(save_point=sp)
		raise
	finally:
		frappe.flags.delivery_schedule_service_write = previous_service_write
	return get_form_schedule_state(so.name, item.name)


def _validate_form_schedule_eligibility(so, item):
	from qcmc_logic.api.sales_order_delivery_eligibility import is_open_sales_order_for_delivery
	if so.docstatus == 0:
		if so.status != "Draft":
			frappe.throw(_("Only draft Sales Orders can be scheduled before submission."))
	elif so.docstatus == 1:
		if not is_open_sales_order_for_delivery(so):
			frappe.throw(_("Submitted Sales Orders must remain open for delivery scheduling."))
	else:
		frappe.throw(_("Cancelled Sales Orders cannot be scheduled."))
	if so.get("is_return") or so.custom_so_type not in ("REGULAR",):
		frappe.throw(_("This Sales Order type is not eligible for delivery scheduling."))
	if not item.warehouse or frappe.db.get_value("Warehouse", item.warehouse, "custom_is_province"):
		frappe.throw(_("Delivery scheduling requires an allowed non-provincial warehouse."))
	if frappe.db.get_value("Warehouse", item.warehouse, "company") != so.company:
		frappe.throw(_("The item's warehouse must belong to the Sales Order company."))
	if item.get("delivered_by_supplier"):
		frappe.throw(_("Supplier-delivered Sales Order Items cannot use operational delivery schedules."))


def _baseline_schedule_entries(so, existing_items, draft_allocated_by_item):
	"""Build only missing per-item initial commitments; no SO commercial fields are changed."""
	entries = []
	for item in so.items:
		if item.name in existing_items or getattr(item, "delivered_by_supplier", False):
			continue
		remaining = Decimal(str(flt(item.qty - item.delivered_qty - draft_allocated_by_item.get(item.name, 0),
			item.precision("qty"))))
		if remaining < 0:
			frappe.throw(_("Delivered and draft-allocated quantity exceeds Sales Order Item {0}.").format(item.item_code))
		if remaining == 0:
			continue
		date = item.delivery_date or so.delivery_date
		if not date:
			frappe.throw(_("Set a Delivery Date on item {0} or its Sales Order before initializing schedules.").format(item.item_code))
		entries.append({"item": item, "delivery_date": date, "planned_qty": remaining})
	return entries


@frappe.whitelist(methods=["POST"])
def initialize_sales_order_delivery_schedules(sales_order):
	"""Initialize missing schedule baselines without changing Sales Order commercial values."""
	so_name = frappe.db.get_value("Sales Order", sales_order, "name")
	if not so_name:
		frappe.throw(_("Sales Order was not found."))
	frappe.db.sql("SELECT name FROM `tabSales Order` WHERE name = %s FOR UPDATE", so_name)
	so = frappe.get_doc("Sales Order", so_name)
	if so.docstatus not in (0, 1) or so.get("is_return"):
		frappe.throw(_("Only active draft or submitted Sales Orders can be scheduled."))
	if so.docstatus == 1:
		from qcmc_logic.api.sales_order_delivery_eligibility import is_open_sales_order_for_delivery
		if not is_open_sales_order_for_delivery(so):
			frappe.throw(_("This Sales Order is not open for delivery scheduling."))
	if so.custom_so_type not in ("REGULAR",):
		frappe.throw(_("This Sales Order type is not eligible for delivery scheduling."))
	_require_sales_access(so)
	for item in so.items:
		_validate_form_schedule_eligibility(so, item)
		_require_sales_access(so, item, require_transact=True)

	# The SO row lock serializes initializers; re-read schedule names only after it.
	existing_rows = frappe.get_all("SO Delivery Schedule", filters={"sales_order": so.name},
		fields=["name", "sales_order_item", "history_status"])
	existing_items = {row.sales_order_item for row in existing_rows}
	for item in so.items:
		_lock_schedules(item.name)
	draft_rows = frappe.db.sql("""
		SELECT dni.so_detail, SUM(dni.qty) AS qty
		FROM `tabDelivery Note Item` dni JOIN `tabDelivery Note` dn ON dn.name = dni.parent
		WHERE dni.against_sales_order = %s AND dni.so_detail IS NOT NULL AND dn.docstatus = 0
		GROUP BY dni.so_detail
	""", so.name, as_dict=True)
	draft_allocated = {row.so_detail: Decimal(str(row.qty or 0)) for row in draft_rows}
	entries = _baseline_schedule_entries(so, existing_items, draft_allocated)
	sp = "initialize_so_delivery_baselines"
	frappe.db.savepoint(sp)
	previous = frappe.flags.get("delivery_schedule_service_write")
	created_docs = []
	try:
		for entry in entries:
			item = entry["item"]
			doc = frappe.get_doc({"doctype": "SO Delivery Schedule", "sales_order": so.name,
				"sales_order_item": item.name, "item_code": item.item_code,
				"warehouse": item.warehouse, "delivery_date": entry["delivery_date"],
				"planned_qty": float(entry["planned_qty"]), "uom": item.uom,
				"conversion_factor": item.conversion_factor,
				"remarks": _("Initial Sales Order delivery commitment")})
			frappe.flags.delivery_schedule_service_write = True
			doc.insert(ignore_permissions=True)
			created_docs.append(doc)
	except Exception:
		frappe.db.rollback(save_point=sp)
		raise
	finally:
		frappe.flags.delivery_schedule_service_write = previous
	return {"sales_order": so.name, "created": [doc.name for doc in created_docs],
		"created_count": len(created_docs), "existing_item_count": len(existing_items),
		"unreconciled_schedules": [row.name for row in existing_rows if row.history_status != "Verified"]}


def _schedule_plan_quantity(value, precision):
	try:
		amount = Decimal(str(value))
	except (InvalidOperation, TypeError, ValueError):
		frappe.throw(_("Enter a valid planned quantity."))
	quantum = Decimal(1).scaleb(-precision)
	if not amount.is_finite() or amount <= 0 or amount.quantize(quantum) != amount:
		frappe.throw(_("Planned quantity must be greater than zero and use the item's allowed precision."))
	return amount


def _validate_original_schedule_fields_unchanged(doc):
	"""Compare every immutable origin/provenance field with its persisted value."""
	original = frappe.db.get_value("SO Delivery Schedule", doc.name,
		list(SCHEDULE_ORIGINAL_FIELDS), as_dict=True)
	if original and any(doc.get(field) != original.get(field) for field in SCHEDULE_ORIGINAL_FIELDS):
		frappe.throw(_("Original schedule and promise values are immutable."), frappe.PermissionError)


def validate_sales_order_plan(doc, method=None):
	"""Keep Sales Order commercial quantities from dropping below saved schedule plans."""
	rows = frappe.get_all("SO Delivery Schedule", filters={"sales_order": doc.name},
		fields=["name", "sales_order_item", "planned_qty"])
	if not rows:
		return
	items = {row.name: row for row in doc.items}
	planned_by_item = {}
	for schedule in rows:
		item = items.get(schedule.sales_order_item)
		if not item:
			frappe.throw(_("Remove or reassign schedule {0} before deleting its Sales Order Item." ).format(schedule.name))
		planned_by_item[item.name] = planned_by_item.get(item.name, Decimal(0)) + Decimal(str(schedule.planned_qty or 0))
	for item_name, planned in planned_by_item.items():
		item = items[item_name]
		remaining = Decimal(str(flt(item.qty - item.delivered_qty, item.precision("qty"))))
		if planned < 0 or planned > remaining:
			frappe.throw(_("Item {0} quantity cannot be reduced below its saved delivery schedule plan ({1})." ).format(item.item_code, planned))
@frappe.whitelist(methods=["POST"])
def redistribute_schedule(source_schedule, qty, delivery_date, expected_modified, remarks):
	"""Sales-authorized schedule transfer; Logistics uses the same internal transfer service after role validation."""
	if not isinstance(remarks, str) or not remarks.strip():
		frappe.throw(_("Enter a reason for the schedule change."))
	source = frappe.get_doc("SO Delivery Schedule", source_schedule)
	so, item = _load_so_item(source.sales_order_item, lock=True)
	_require_sales_access(so, item, require_transact=True)
	return _apply_schedule_transfer_locked(source, so, item, qty, delivery_date,
		expected_modified, remarks, allow_finalized_correction=False)


def _apply_schedule_transfer_locked(source, so, item, qty, delivery_date, expected_modified, remarks,
		allow_finalized_correction=False, allow_cancelled_history=False):
	"""Atomically move schedule Total and promise attribution to a new, distinct destination row."""
	_lock_schedules(item.name)
	source.reload()
	if str(source.modified) != str(expected_modified):
		frappe.throw(_("Schedule changed. Refresh before applying."), frappe.TimestampMismatchError)
	state = quantity_state(item.name, lock=True, check_sales_access=False)
	if source.history_status != "Verified":
		frappe.throw(_("Reconcile the source schedule before transferring its commitment."))
	amount = _decimal(qty, state["precision"])
	if delivery_date == str(source.delivery_date):
		frappe.throw(_("Choose a different delivery date."))
	if amount > state["available_scheduled_qty"].get(source.name, Decimal(0)):
		frappe.throw(_("Cannot move quantity already allocated to a draft Delivery Note."))
	if not allow_finalized_correction:
		_assert_schedule_plan_editable(source)
	elif _has_protected_schedule_delivery(source.name) and not allow_cancelled_history:
		frappe.throw(_("Schedule quantities committed to a protected Delivery Note cannot be moved."))
	if not delivery_date or getdate(delivery_date) < getdate(so.transaction_date):
		frappe.throw(_("Choose a valid destination date."))
	promise_attributions = _allocate_promise_attributions(source.name, amount)
	transaction_id = hashlib.sha256(
		f"transfer|{source.name}|{expected_modified}|{delivery_date}|{amount}".encode()).hexdigest()
	sp = "delivery_schedule_transfer"
	frappe.db.savepoint(sp)
	previous_transfer_context = frappe.flags.get("delivery_schedule_transfer_context")
	previous_service_write = frappe.flags.get("delivery_schedule_service_write")
	try:
		frappe.flags.delivery_schedule_service_write = True
		source.reload()
		source_before = Decimal(str(source.current_total or source.planned_qty or 0))
		source.planned_qty = flt(source.planned_qty) - float(amount)
		_clear_schedule_confirmation(source)
		source.save(ignore_permissions=True)
		source_after = Decimal(str(source.current_total or source.planned_qty or 0))
		frappe.flags.delivery_schedule_transfer_context = {"promise_date": promise_attributions[0][1]}
		dest_doc = frappe.get_doc({"doctype":"SO Delivery Schedule", "sales_order":so.name,
			"sales_order_item":item.name, "item_code":item.item_code, "warehouse":source.warehouse,
			"delivery_date":delivery_date, "planned_qty":float(amount), "uom":item.uom,
			"conversion_factor":item.conversion_factor, "remarks":remarks.strip(),
			"source_schedule": source.name, "source_date": source.delivery_date,
			"movement_transaction_id": transaction_id})
		dest_doc.insert(ignore_permissions=True)
		destination_before = Decimal(0)
		destination_after = Decimal(str(dest_doc.current_total or dest_doc.planned_qty or 0))
		for index, (promise_commitment, promise_date, promise_qty) in enumerate(promise_attributions):
			common = {"sales_order": so.name, "sales_order_item": item.name, "quantity": promise_qty,
				"uom": item.uom, "promise_date": promise_date, "promise_qty": promise_qty,
				"promise_commitment": promise_commitment,
				"reason": remarks.strip(), "transaction_id": transaction_id}
			append_schedule_movement(operation_type="Transfer Out", source_schedule=source.name,
				destination_schedule=dest_doc.name, source_before=source_before, source_after=source_after,
				destination_before=destination_before, destination_after=destination_after,
				idempotency_key=f"{transaction_id}:out:{index}", **common)
			append_schedule_movement(operation_type="Transfer In", source_schedule=source.name,
				destination_schedule=dest_doc.name, source_before=source_before, source_after=source_after,
				destination_before=destination_before, destination_after=destination_after,
				idempotency_key=f"{transaction_id}:in:{index}", **common)
	except Exception:
		frappe.db.rollback(save_point=sp)
		raise
	finally:
		frappe.flags.delivery_schedule_service_write = previous_service_write
		frappe.flags.delivery_schedule_transfer_context = previous_transfer_context
	return {"source": source.name, "destination": dest_doc.name, "qty": float(amount),
		"transaction_id": transaction_id, "state": quantity_state(item.name, check_sales_access=False)}


def _adjust_schedule_total(schedule, new_total, reason, *, related_delivery_note=None,
		idempotency_key=None, clear_confirmation=True):
	"""Change only the operational Total and record the adjustment against its promise cohort."""
	so_item = frappe.db.get_value("SO Delivery Schedule", schedule.name, "sales_order_item")
	item_doc = frappe.get_doc("Sales Order Item", so_item)
	precision = item_doc.precision("qty")
	before = Decimal(str(schedule.current_total if schedule.current_total is not None else schedule.planned_qty or 0))
	after = Decimal(str(new_total))
	delta = after - before
	if not delta:
		return schedule
	if not after.is_finite() or after < 0 or after.quantize(Decimal(1).scaleb(-precision)) != after:
		frappe.throw(_("Adjusted Total must be non-negative and use the item's allowed precision."))
	if not reason or not reason.strip():
		frappe.throw(_("Enter a reason for the schedule adjustment."))
	if schedule.history_status != "Verified":
		frappe.throw(_("Reconcile the schedule before changing its Total."))
	if delta < 0:
		state = quantity_state(so_item, lock=True, check_sales_access=False)
		if -delta > state["available_scheduled_qty"].get(schedule.name, Decimal(0)):
			frappe.throw(_("The reduction would move quantity allocated to an active Delivery Note."))
		attributions = _allocate_promise_attributions(schedule.name, -delta)
	else:
		attributions = [(schedule.name, schedule.original_promise_date or schedule.original_delivery_date,
			delta)]
	transaction_id = idempotency_key or hashlib.sha256(
		f"adjust|{schedule.name}|{schedule.modified}|{after}|{reason.strip()}".encode()).hexdigest()
	prior = frappe.db.get_value("Delivery Schedule Movement", {"transaction_id": transaction_id},
		["destination_schedule", "source_schedule"], as_dict=True)
	if prior:
		return frappe.get_doc("SO Delivery Schedule", prior.destination_schedule or prior.source_schedule)
	sp = "delivery_schedule_quantity_adjustment"
	frappe.db.savepoint(sp)
	previous = frappe.flags.get("delivery_schedule_service_write")
	try:
		frappe.flags.delivery_schedule_service_write = True
		if clear_confirmation:
			_clear_schedule_confirmation(schedule)
		schedule.planned_qty = float(after)
		schedule.save(ignore_permissions=True)
		for index, (commitment, promise_date, promise_qty) in enumerate(attributions):
			append_schedule_movement(operation_type="Quantity Adjustment", sales_order=schedule.sales_order,
				sales_order_item=so_item, quantity=abs(promise_qty), uom=schedule.uom,
				promise_date=promise_date, promise_qty=abs(promise_qty), promise_commitment=commitment,
				reason=reason.strip(), source_schedule=schedule.name if delta < 0 else None,
				destination_schedule=schedule.name if delta > 0 else None,
				source_before=before if delta < 0 else None,
				source_after=after if delta < 0 else None,
				destination_before=before if delta > 0 else None,
				destination_after=after if delta > 0 else None,
				related_delivery_note=related_delivery_note, transaction_id=transaction_id,
				idempotency_key=f"{transaction_id}:{index}")
	except Exception:
		frappe.db.rollback(save_point=sp)
		raise
	finally:
		frappe.flags.delivery_schedule_service_write = previous
	return schedule


def _transfer_to_new_schedule(source, so, item, qty, delivery_date, reason, *,
		related_delivery_note=None, related_dn_item=None,
		clear_source_confirmation=True, allow_protected=False,
		reservation_qty=0, idempotency_key=None):
	"""Append a source-to-new-row transfer; callers must lock and authorize both records."""
	if source.history_status != "Verified":
		frappe.throw(_("Reconcile the source schedule before transferring its commitment."))
	amount = _decimal(qty, item.precision("qty"))
	state = quantity_state(item.name, lock=True, check_sales_access=False)
	available = state["available_scheduled_qty"].get(source.name, Decimal(0)) + Decimal(str(reservation_qty or 0))
	if amount > available:
		frappe.throw(_("Cannot move quantity already allocated to an active Delivery Note."))
	if not allow_protected and _has_protected_schedule_delivery(source.name):
		frappe.throw(_("Schedule quantities committed to a protected Delivery Note cannot be moved."))
	if getdate(delivery_date) < getdate(so.transaction_date):
		frappe.throw(_("Choose a valid destination date."))
	attrs = _allocate_promise_attributions(source.name, amount)
	tx = idempotency_key or hashlib.sha256(
		f"transfer|{source.name}|{source.modified}|{delivery_date}|{amount}".encode()).hexdigest()
	prior = frappe.db.get_value("Delivery Schedule Movement", {"transaction_id": tx}, "destination_schedule")
	if prior:
		return frappe.get_doc("SO Delivery Schedule", prior), tx
	sp = "delivery_schedule_atomic_transfer"
	frappe.db.savepoint(sp)
	previous_service_write = frappe.flags.get("delivery_schedule_service_write")
	previous_context = frappe.flags.get("delivery_schedule_transfer_context")
	try:
		frappe.flags.delivery_schedule_service_write = True
		before = Decimal(str(source.current_total if source.current_total is not None else source.planned_qty or 0))
		after = before - amount
		if clear_source_confirmation:
			_clear_schedule_confirmation(source)
		source.planned_qty = float(after)
		source.save(ignore_permissions=True)
		frappe.flags.delivery_schedule_transfer_context = {"promise_date": attrs[0][1]}
		destination = frappe.get_doc({"doctype": "SO Delivery Schedule", "sales_order": so.name,
			"sales_order_item": item.name, "item_code": item.item_code, "warehouse": source.warehouse,
			"delivery_date": delivery_date, "planned_qty": float(amount), "uom": item.uom,
			"conversion_factor": item.conversion_factor, "remarks": reason.strip(),
			"source_schedule": source.name, "source_date": source.delivery_date,
			"movement_transaction_id": tx})
		destination.insert(ignore_permissions=True)
		for index, (commitment, promise_date, promise_qty) in enumerate(attrs):
			common = {"sales_order": so.name, "sales_order_item": item.name,
				"quantity": promise_qty, "uom": item.uom, "promise_date": promise_date,
				"promise_qty": promise_qty, "promise_commitment": commitment,
				"reason": reason.strip(), "transaction_id": tx,
				"related_delivery_note": related_delivery_note,
				"related_dn_item": related_dn_item}
			append_schedule_movement(operation_type="Transfer Out", source_schedule=source.name,
				destination_schedule=destination.name, source_before=before, source_after=after,
				destination_before=0, destination_after=amount,
				idempotency_key=f"{tx}:out:{index}", **common)
			append_schedule_movement(operation_type="Transfer In", source_schedule=source.name,
				destination_schedule=destination.name, source_before=before, source_after=after,
				destination_before=0, destination_after=amount,
				idempotency_key=f"{tx}:in:{index}", **common)
	except Exception:
		frappe.db.rollback(save_point=sp)
		raise
	finally:
		frappe.flags.delivery_schedule_service_write = previous_service_write
		frappe.flags.delivery_schedule_transfer_context = previous_context
	return destination, tx


def _has_protected_schedule_delivery(schedule_name):
	"""A draft without DR number/invoice is movable; submitted or progressed DNs are protected."""
	return bool(frappe.db.sql("""
		SELECT dn.name FROM `tabDelivery Note Item` dni
		JOIN `tabDelivery Note` dn ON dn.name = dni.parent
		LEFT JOIN `tabSales Invoice Item` sii ON sii.dn_detail = dni.name
		LEFT JOIN `tabSales Invoice` si ON si.name = sii.parent AND si.docstatus < 2
		WHERE dni.custom_so_delivery_schedule = %s AND (
			dn.docstatus IN (1, 2) OR IFNULL(dn.custom_dr_number, '') != '' OR si.name IS NOT NULL
			OR IFNULL(dn.workflow_state, '') NOT IN ('', 'Draft', 'For Stock Confirmation')
		) LIMIT 1
	""", schedule_name))


def _has_active_sales_invoice(delivery_note):
	item_names = frappe.get_all("Delivery Note Item", filters={"parent": delivery_note}, pluck="name")
	if not item_names:
		return False
	invoice_names = frappe.get_all("Sales Invoice Item", filters={"dn_detail": ["in", item_names]}, pluck="parent")
	return bool(invoice_names and frappe.get_all(
		"Sales Invoice", filters={"name": ["in", invoice_names], "docstatus": ["<", 2]}, pluck="name"
	))


def _split_unfinalized_schedule_balance(schedule, so, so_item, final_qty, precision):
	planned = Decimal(str(schedule.planned_qty or 0))
	balance = planned - final_qty
	if balance < 0:
		frappe.throw(_("Final quantity exceeds planned quantity for schedule {0}.").format(schedule.name))
	if not balance:
		return
	promise_attributions = _allocate_promise_attributions(schedule.name, balance)
	transaction_id = hashlib.sha256(
		f"sales-finalization-split|{schedule.name}|{schedule.modified}|{final_qty}".encode()).hexdigest()
	previous = frappe.flags.get("delivery_schedule_service_write")
	previous_transfer_context = frappe.flags.get("delivery_schedule_transfer_context")
	frappe.flags.delivery_schedule_service_write = True
	try:
		source_before = Decimal(str(schedule.current_total or schedule.planned_qty or 0))
		schedule.planned_qty = float(final_qty)
		schedule.save(ignore_permissions=True)
		frappe.flags.delivery_schedule_transfer_context = {"promise_date": promise_attributions[0][1]}
		destination = frappe.get_doc({"doctype": "SO Delivery Schedule", "sales_order": so.name,
			"sales_order_item": so_item.name, "item_code": so_item.item_code,
			"warehouse": so_item.warehouse, "delivery_date": schedule.delivery_date,
			"planned_qty": float(balance), "uom": so_item.uom,
			"conversion_factor": so_item.conversion_factor,
			"remarks": _("Unfinalized balance split from schedule {0}").format(schedule.name),
			"source_schedule": schedule.name, "source_date": schedule.delivery_date,
			"movement_transaction_id": transaction_id}).insert(ignore_permissions=True)
		destination_before = Decimal(0)
		destination_after = Decimal(str(destination.current_total or destination.planned_qty or 0))
		for index, (promise_commitment, promise_date, promise_qty) in enumerate(promise_attributions):
			common = {"sales_order": so.name, "sales_order_item": so_item.name,
				"quantity": promise_qty, "uom": so_item.uom, "promise_date": promise_date,
				"promise_commitment": promise_commitment,
				"promise_qty": promise_qty,
				"reason": _("Sales finalization retained this quantity as pending demand."),
				"source_schedule": schedule.name, "destination_schedule": destination.name,
				"source_before": source_before, "source_after": schedule.current_total,
				"destination_before": destination_before, "destination_after": destination_after,
				"transaction_id": transaction_id}
			append_schedule_movement(operation_type="Sales Finalization Split Out",
				idempotency_key=f"{transaction_id}:out:{index}", **common)
			append_schedule_movement(operation_type="Sales Finalization Split In",
				idempotency_key=f"{transaction_id}:in:{index}", **common)
	finally:
		frappe.flags.delivery_schedule_service_write = previous
		frappe.flags.delivery_schedule_transfer_context = previous_transfer_context


def _notify_schedule_change(schedule):
	from qcmc_logic.api.delivery_workbench_collaboration import notify_change

	notify_change(schedule)


@frappe.whitelist(methods=["POST"])
def create_draft_delivery_notes(schedule_quantities, expected_schedule_state):
	"""Create or extend one draft DN per selected v2 schedule; never post stock."""
	if isinstance(schedule_quantities, str):
		schedule_quantities = frappe.parse_json(schedule_quantities)
	if isinstance(expected_schedule_state, str):
		expected_schedule_state = frappe.parse_json(expected_schedule_state)
	if not isinstance(schedule_quantities, dict) or not schedule_quantities:
		frappe.throw(_("Select at least one delivery schedule."))
	if not isinstance(expected_schedule_state, dict) or set(expected_schedule_state) != set(schedule_quantities):
		frappe.throw(_("Schedule state is missing. Refresh before creating Delivery Notes."))
	if any(not isinstance(value, dict) for value in expected_schedule_state.values()):
		frappe.throw(_("Schedule state is invalid. Refresh before creating Delivery Notes."))

	requested = {str(name): value for name, value in schedule_quantities.items()}
	locked_rows = frappe.db.sql("""
		SELECT s.name, s.sales_order, s.sales_order_item
		FROM `tabSO Delivery Schedule` s
		JOIN `tabSales Order` so ON so.name = s.sales_order
		WHERE s.name IN %(names)s
		ORDER BY so.name, s.name
		FOR UPDATE
	""", {"names": tuple(sorted(requested))}, as_dict=True)
	if len(locked_rows) != len(requested):
		frappe.throw(_("One or more selected schedules no longer exist."))
	schedules = {row.name: frappe.get_doc("SO Delivery Schedule", row.name) for row in locked_rows}
	parents = sorted({doc.sales_order for doc in schedules.values()})

	from erpnext.selling.doctype.sales_order.sales_order import make_delivery_note
	from erpnext.stock.doctype.packed_item.packed_item import make_packing_list
	created = []
	new_schedule_entries = []
	sp = "create_schedule_delivery_notes"
	frappe.db.savepoint(sp)
	try:
		for name in sorted(schedules):
			schedule = frappe.get_doc("SO Delivery Schedule", name)
			so, so_item = _load_so_item(schedule.sales_order_item)
			_require_sales_access(so, so_item, require_transact=True)
			if so.name != schedule.sales_order:
				frappe.throw(_("Schedule Sales Order link is inconsistent."))
			from qcmc_logic.api.sales_order_delivery_eligibility import is_open_sales_order_for_delivery
			if not is_open_sales_order_for_delivery(so) or so.custom_so_type not in ("REGULAR",):
				frappe.throw(_("Only eligible open FOB Sales Orders can proceed to Delivery Note."))
			if not so_item.warehouse or frappe.db.get_value("Warehouse", so_item.warehouse, "custom_is_province"):
				frappe.throw(_("Delivery Notes require an allowed non-provincial warehouse."))
			if (schedule.get("confirmation_status") != "Finalized"
				or not schedule.get("sales_confirmed_by")
				or not schedule.get("logistics_confirmed_by")):
				frappe.throw(_("Only schedules confirmed by both Sales and Logistics can proceed to Delivery Note."))
			if schedule.final_qty is None:
				frappe.throw(_("Final quantity is missing for schedule {0}.").format(name))
			state = quantity_state(so_item.name, lock=True)
			expected = expected_schedule_state[name]
			if (str(schedule.modified) != str(expected.get("modified"))
				or _snapshot_decimal(expected.get("draft_allocated_qty")) != state["draft_allocated_by_schedule"].get(name, Decimal(0))):
				frappe.throw(_("Schedule {0} changed since it was displayed. Refresh before retrying.").format(name), frappe.TimestampMismatchError)
			available = state["available_scheduled_qty"].get(name, Decimal(0))
			qty = _decimal(requested[name], state["precision"])
			if qty != Decimal(str(flt(schedule.final_qty, state["precision"]))):
				frappe.throw(_("Delivery Note quantity must equal the jointly finalized quantity for schedule {0}.").format(name))

			# The finalized quantity is the cap. A single unnumbered Draft may absorb
			# only the remaining confirmed amount; stale retries cannot duplicate it.
			linked_active_notes = _locked_schedule_delivery_notes(name)
			_validate_no_submitted_schedule_delivery(linked_active_notes, name)
			all_linked_names = set(frappe.get_all("Delivery Note Item",
				filters={DN_SCHEDULE_FIELD: name}, pluck="parent"))
			cancelled_names = frappe.get_all("Delivery Note",
				filters={"name": ["in", tuple(sorted(all_linked_names))], "docstatus": 2}, pluck="name") if all_linked_names else []
			if cancelled_names:
				frappe.throw(_("Schedule {0} has cancelled Delivery Note history. Create a separately authorized replacement schedule.").format(name))
			existing_drafts = [row.name for row in linked_active_notes if row.docstatus == 0]
			if len(existing_drafts) > 1:
				frappe.throw(_("Schedule {0} already has multiple draft Delivery Notes. Resolve those duplicates before proceeding.").format(name))
			if existing_drafts:
				existing = frappe.get_doc("Delivery Note", existing_drafts[0])
				matching = [row for row in existing.items if row.get(DN_SCHEDULE_FIELD) == name and row.so_detail == so_item.name]
				allocated = state["draft_allocated_by_schedule"].get(name, Decimal(0))
				additional = qty - allocated
				if (existing.workflow_state != "Draft" or existing.get("custom_dr_number")
					or _has_active_sales_invoice(existing.name) or len(matching) != 1
					or Decimal(str(flt(matching[0].qty, state["precision"]))) != allocated):
					frappe.throw(_("Schedule {0} is linked to a finalized, invoiced, or inconsistent Delivery Note and cannot be consolidated.").format(name))
				if additional < 0 or additional > available:
					frappe.throw(_("The existing Draft allocation plus this request exceeds the jointly finalized quantity for schedule {0}.").format(name))
				if additional:
					if any(row.against_sales_order != so.name for row in existing.items):
						frappe.throw(_("Delivery Note {0} contains another Sales Order and cannot be consolidated.").format(existing.name))
					existing.check_permission("read")
					matching[0].qty = float(qty)
					existing.run_method("calculate_taxes_and_totals")
					make_packing_list(existing)
					# This exact child-row adjustment is authorized by the schedule service;
					# Sales Order and commercial permissions are not bypassed or modified.
					existing.save(ignore_permissions=True)
					existing.add_comment("Info", _("Additional quantity for finalized schedule {0} was consolidated on this unnumbered Draft Delivery Note.").format(name))
				_notify_schedule_change(schedule)
				created.append(existing.name)
				continue
			if qty > available:
				frappe.throw(_("Requested quantity exceeds available quantity for schedule {0}.").format(name))
			new_schedule_entries.append((schedule, so, so_item, qty))

		# Keep compatible rows together on one draft: same SO, schedule date and
		# warehouse. Each schedule remains a separate Delivery Note Item link.
		groups = {}
		for entry in new_schedule_entries:
			schedule, so, so_item, _qty = entry
			key = _delivery_note_compatibility_key(so, schedule, so_item)
			groups.setdefault(key, []).append(entry)
		for (so_name, _delivery_date, _warehouse), entries in sorted(groups.items()):
			so = entries[0][1]
			so_item_names = sorted({entry[2].name for entry in entries})
			dn = make_delivery_note(so_name, kwargs={"filtered_children": so_item_names})
			if not dn:
				frappe.throw(_("ERPNext could not prepare a Delivery Note for Sales Order {0}.").format(so_name))
			payloads = _delivery_note_schedule_item_payloads(
				dn.items, [(schedule, so_item, qty) for schedule, _so, so_item, qty in entries])
			dn.set("items", [])
			for payload in payloads:
				dn.append("items", payload)
			dn.custom_sales_order = so_name
			dn.run_method("calculate_taxes_and_totals")
			make_packing_list(dn)
			dn.workflow_state = "Draft"
			dn.insert()
			created.append(dn.name)
			for schedule, _so, _so_item, _qty in entries:
				_notify_schedule_change(schedule)
	except Exception:
		try:
			frappe.db.rollback(save_point=sp)
		except Exception:
			# A concurrent name-series conflict can invalidate the savepoint. Abort
			# the request transaction but preserve the original exception.
			frappe.db.rollback()
		raise
	return {"delivery_notes": created, "message": _("Created Draft Delivery Note(s): {0}").format(", ".join(created))}


@frappe.whitelist(methods=["POST"])
def reconcile_delivered_quantity(schedule, delivery_note, dn_detail, actual_qty, deferred_date,
		expected_modified, expected_dn_modified):
	"""Reconcile a returned truck's quantity before submission; defer its balance."""
	if "Stock Confirm User" not in frappe.get_roles():
		frappe.throw(_("Stock Confirm User permission is required."), frappe.PermissionError)
	identity = frappe.db.get_value("SO Delivery Schedule", schedule,
		["sales_order", "sales_order_item", "warehouse"], as_dict=True)
	if not identity:
		frappe.throw(_("Delivery schedule was not found."))
	so = frappe.get_doc("Sales Order", identity.sales_order, for_update=True)
	so.check_permission("read")
	from qcmc_logic.api.sales_order_delivery_eligibility import is_open_sales_order_for_delivery
	if (not is_open_sales_order_for_delivery(so)
		or so.custom_so_type not in ("REGULAR",)):
		frappe.throw(_("Only an active, eligible Sales Order can be reconciled."))
	schedule_doc = frappe.get_doc("SO Delivery Schedule", schedule, for_update=True)
	if str(schedule_doc.modified) != str(expected_modified):
		frappe.throw(_("Schedule changed in another session. Refresh before reconciling."), frappe.TimestampMismatchError)
	if (schedule_doc.confirmation_status != "Finalized" or not schedule_doc.sales_confirmed_by
		or not schedule_doc.logistics_confirmed_by):
		frappe.throw(_("The originating schedule lacks both departmental confirmations."))
	dn = frappe.get_doc("Delivery Note", delivery_note, for_update=True)
	dn.check_permission("read")
	if str(dn.modified) != str(expected_dn_modified):
		frappe.throw(_("Delivery Note changed in another session. Refresh before reconciling."), frappe.TimestampMismatchError)
	if dn.docstatus != 0 or dn.workflow_state != "To Deliver and Bill":
		frappe.throw(_("Only a Draft Delivery Note released for delivery can be reconciled."))
	if not dn.get("custom_dr_number"):
		frappe.throw(_("Delivery Note must have its DR number assigned before reconciliation."))
	dn_details = [row.name for row in dn.items]
	invoice_details = frappe.get_all("Sales Invoice Item", filters={"dn_detail": ["in", dn_details]}, pluck="parent")
	if invoice_details and frappe.get_all("Sales Invoice", filters={"name": ["in", invoice_details], "docstatus": ["<", 2]}, pluck="name"):
		frappe.throw(_("A linked Sales Invoice exists. Resolve it before changing Delivery Note quantities."))
	item = next((row for row in dn.items if row.name == dn_detail), None)
	linked_items = frappe.get_all("Delivery Note Item",
		filters={DN_SCHEDULE_FIELD: schedule}, fields=["name", "parent"])
	if len(linked_items) != 1 or linked_items[0].name != dn_detail or linked_items[0].parent != delivery_note:
		frappe.throw(_("Schedule must have exactly one active Delivery Note item before reconciliation."))
	if (dn.company != so.company or dn.customer != so.customer or not item
		or dn.get("custom_sales_order") != so.name
		or any(row.against_sales_order != so.name for row in dn.items)
		or item.get(DN_SCHEDULE_FIELD) != schedule or item.so_detail != identity.sales_order_item
		or item.against_sales_order != identity.sales_order or item.warehouse != identity.warehouse
		or item.item_code != schedule_doc.item_code or schedule_doc.sales_order != so.name):
		frappe.throw(_("Delivery Note item does not match the selected schedule."))
	if (frappe.db.get_value("Warehouse", item.warehouse, "company") != so.company
		or frappe.db.get_value("Warehouse", item.warehouse, "custom_is_province")):
		frappe.throw(_("Delivery Note must use an allowed non-provincial warehouse belonging to the Sales Order company."))
	from qcmc_logic.api.delivery_confirmation_service import _validate_warehouse_access
	_validate_warehouse_access(item.warehouse, require_transact=True)
	if not frappe.has_permission("Company", "read", so.company):
		frappe.throw(_("Company read access is required."), frappe.PermissionError)
	so_item = next((row for row in so.items if row.name == identity.sales_order_item), None)
	if not so_item:
		frappe.throw(_("Original Sales Order Item was not found."))
	try:
		new_qty = Decimal(str(actual_qty))
		quantum = Decimal(1).scaleb(-item.precision("qty"))
	except (InvalidOperation, TypeError, ValueError):
		frappe.throw(_("Enter a valid actual delivered quantity."))
	old_qty = Decimal(str(flt(item.qty, item.precision("qty"))))
	if Decimal(str(flt(schedule_doc.planned_qty, item.precision("qty")))) < old_qty:
		frappe.throw(_("Schedule plan is below its current Delivery Note allocation. Resolve the allocation mismatch first."))
	if not new_qty.is_finite() or new_qty <= 0 or new_qty.quantize(quantum) != new_qty or new_qty > old_qty:
		frappe.throw(_("Actual quantity must be positive, use item precision, and not exceed the authorized DN quantity."))
	if new_qty == old_qty:
		return {"changed": False, "delivery_note": dn.name, "quantity": float(new_qty)}
	if not deferred_date or getdate(deferred_date) <= getdate(schedule_doc.delivery_date):
		frappe.throw(_("Choose a later date for the undelivered quantity."))
	# This endpoint has already enforced Stock Confirm User, SO read, Company
	# read, and warehouse transaction scope above. Do not require the Sales
	# Coordinator role a second time through the default quantity-state path.
	state = _get_logistics_reconciliation_quantity_state(so_item.name)
	if schedule_doc.final_qty is None or old_qty > Decimal(str(flt(schedule_doc.final_qty, state["precision"]))):
		frappe.throw(_("Delivery Note quantity exceeds its finalized schedule allocation."))
	delta = old_qty - new_qty
	destination = next((row for row in state["schedules"] if row.name != schedule and
		str(row.delivery_date) == str(deferred_date) and row.warehouse == schedule_doc.warehouse), None)
	if destination:
		frappe.throw(_("Choose a new date with no existing schedule. Distinct promise rows must remain separate."))
	sp = "reconcile_v2_delivery_quantity"
	frappe.db.savepoint(sp)
	previous = frappe.flags.get("delivery_schedule_service_write")
	try:
		frappe.flags.delivery_schedule_service_write = True
		item.qty = float(new_qty)
		dn.run_method("calculate_taxes_and_totals")
		dn.save(ignore_permissions=True)
		_transfer_to_new_schedule(schedule_doc, so, so_item, delta, deferred_date,
			_("Short delivery on {0}; {1} deferred to {2}.").format(dn.name, delta, deferred_date),
			related_delivery_note=dn.name, related_dn_item=dn_detail,
			clear_source_confirmation=False, allow_protected=True,
			idempotency_key=f"short-delivery:{dn.name}:{dn_detail}:{expected_modified}:{new_qty}:{deferred_date}")
		schedule_doc.reload()
		schedule_doc.logistics_committed_qty = min(Decimal(str(schedule_doc.logistics_committed_qty or 0)),
			Decimal(str(schedule_doc.current_total or 0)))
		if schedule_doc.final_qty is not None:
			schedule_doc.final_qty = min(Decimal(str(schedule_doc.final_qty)), Decimal(str(schedule_doc.current_total or 0)))
		schedule_doc.save(ignore_permissions=True)
		dn.add_comment("Info", _("Reconciled delivered quantity from {0} to {1}; {2} was deferred to {3}.").format(old_qty, new_qty, delta, deferred_date))
	except Exception:
		frappe.db.rollback(save_point=sp)
		raise
	finally:
		frappe.flags.delivery_schedule_service_write = previous
	return {"changed": True, "delivery_note": dn.name, "quantity": float(new_qty),
		"deferred_qty": float(delta), "deferred_date": str(deferred_date)}


def _get_logistics_reconciliation_quantity_state(so_item_name):
	"""Use the logistics-authorized read path after reconciliation scope checks."""
	return quantity_state(so_item_name, lock=True, check_sales_access=False)


@frappe.whitelist(methods=["POST"])
def authorize_cancelled_schedule_replacement(schedule_name, delivery_date, reason, expected_modified):
	"""Transfer demand restored by canceled DNs to one new, Pending schedule."""
	if "Sales Coordinator" not in frappe.get_roles():
		frappe.throw(_("Sales Coordinator permission is required."), frappe.PermissionError)
	if not isinstance(reason, str) or not reason.strip():
		frappe.throw(_("Enter the replacement authorization reason."))
	if len(reason.strip()) > 1000:
		frappe.throw(_("Replacement reason cannot exceed 1000 characters."))

	identity = frappe.db.get_value("SO Delivery Schedule", schedule_name,
		["sales_order_item", "sales_order"], as_dict=True)
	if not identity:
		frappe.throw(_("Schedule was not found."))
	so, so_item = _load_so_item(identity.sales_order_item, lock=True)
	from qcmc_logic.api.sales_order_delivery_eligibility import is_open_sales_order_for_delivery
	if (so.name != identity.sales_order or not is_open_sales_order_for_delivery(so)
		or so.custom_so_type not in ("REGULAR",)):
		frappe.throw(_("Only an open, eligible FOB Sales Order can authorize replacement demand."))
	_require_sales_access(so, so_item, require_transact=True)

	frappe.db.sql("SELECT name FROM `tabSO Delivery Schedule` WHERE name = %s FOR UPDATE", schedule_name)
	row = frappe.get_doc("SO Delivery Schedule", schedule_name)
	if str(row.modified) != str(expected_modified):
		frappe.throw(_("Schedule changed in another session. Refresh before authorizing replacement."),
			frappe.TimestampMismatchError)
	if (row.sales_order != so.name or row.sales_order_item != so_item.name
		or row.item_code != so_item.item_code or row.warehouse != so_item.warehouse):
		frappe.throw(_("Schedule no longer matches its Sales Order Item."))
	if not delivery_date or getdate(delivery_date) < getdate(so.transaction_date):
		frappe.throw(_("Choose a delivery date on or after the Sales Order date."))
	if str(delivery_date) == str(row.delivery_date):
		frappe.throw(_("Choose a new delivery date for the replacement schedule."))

	history = frappe.db.sql("""
		SELECT dn.name AS delivery_note, dn.docstatus, dni.name AS dn_detail, dni.qty
		FROM `tabDelivery Note Item` dni
		JOIN `tabDelivery Note` dn ON dn.name = dni.parent
		WHERE dni.custom_so_delivery_schedule = %s
		ORDER BY dn.name, dni.name
		FOR UPDATE
	""", schedule_name, as_dict=True)
	if not history:
		frappe.throw(_("This schedule has no canceled Delivery Note history to replace."))
	if any(int(entry.docstatus) != 2 for entry in history):
		frappe.throw(_("Replacement is allowed only after every linked Delivery Note is canceled."))
	dn_names = sorted({entry.delivery_note for entry in history})
	for dn_name in dn_names:
		frappe.db.sql("SELECT name FROM `tabDelivery Note` WHERE name = %s FOR UPDATE", dn_name)
	detail_names = [entry.dn_detail for entry in history]
	invoice_names = frappe.get_all("Sales Invoice Item",
		filters={"dn_detail": ["in", detail_names]}, pluck="parent")
	if invoice_names and frappe.get_all("Sales Invoice",
		filters={"name": ["in", sorted(set(invoice_names))], "docstatus": ["<", 2]}, pluck="name"):
		frappe.throw(_("A Sales Invoice is still active for a canceled Delivery Note; resolve it before replacement."))
	precision = so_item.precision("qty")
	restored = sum((Decimal(str(flt(entry.qty, precision))) for entry in history), Decimal(0))
	planned = Decimal(str(flt(row.planned_qty, precision)))
	if restored <= 0 or planned != restored:
		frappe.throw(_("Restored schedule quantity does not match canceled Delivery Note history. Reconcile the schedule before replacement."))
	if row.confirmation_status != "Finalized" or Decimal(str(flt(row.final_qty, precision))) != restored:
		frappe.throw(_("Only the fully restored finalized quantity can be replaced."))
	if frappe.db.exists("SO Delivery Schedule", {
		"sales_order_item": so_item.name, "warehouse": row.warehouse, "delivery_date": delivery_date,
	}):
		frappe.throw(_("A schedule already exists for this Sales Order Item and date. Choose another date."))

	replacement, transaction_id = _transfer_to_new_schedule(row, so, so_item, restored,
		delivery_date, reason.strip(), allow_protected=True,
		idempotency_key=f"cancel-replacement:{row.name}:{expected_modified}:{delivery_date}:{restored}")
	return {"source": row.name, "replacement": replacement.name,
		"quantity": float(restored), "delivery_date": str(delivery_date),
		"transaction_id": transaction_id}


def _consolidate_schedule_draft(existing, schedule_name, so_item_name, qty):
	if existing.docstatus != 0 or existing.workflow_state != "For Stock Confirmation":
		frappe.throw(_("Delivery Note {0} has been finalized by Sales or submitted for delivery. Do not add quantity to it.").format(existing.name))
	matches = [row for row in existing.items if row.get(DN_SCHEDULE_FIELD) == schedule_name and row.so_detail == so_item_name]
	if len(matches) != 1:
		frappe.throw(_("Delivery Note {0} does not have exactly one matching item for schedule {1}.").format(existing.name, schedule_name))
	item = matches[0]
	item.qty = float(Decimal(str(item.qty)) + qty)
	_reset_logistics_confirmation(item)
	_reset_sales_confirmation(item)
	existing.run_method("calculate_taxes_and_totals")
	from erpnext.stock.doctype.packed_item.packed_item import make_packing_list
	make_packing_list(existing)
	existing.save()
	existing.add_comment("Info", _("Additional quantity was consolidated onto the existing draft for schedule {0}; Logistics and Sales review are required again.").format(schedule_name))


def _locked_schedule_delivery_notes(schedule_name):
	"""Return and lock non-cancelled DNs already allocated to one schedule."""
	rows = frappe.db.sql("""
		SELECT DISTINCT dn.name, dn.docstatus
		FROM `tabDelivery Note` dn
		JOIN `tabDelivery Note Item` dni ON dni.parent = dn.name
		WHERE dni.custom_so_delivery_schedule = %s AND dn.docstatus IN (0, 1)
		ORDER BY dn.name
	""", schedule_name, as_dict=True)
	unique = {row.name: int(row.docstatus) for row in rows}
	for name in sorted(unique):
		frappe.db.sql("SELECT name FROM `tabDelivery Note` WHERE name = %s FOR UPDATE", name)
	return [frappe._dict(name=name, docstatus=unique[name]) for name in sorted(unique)]


def _validate_no_submitted_schedule_delivery(linked_notes, schedule_name):
	if any(int(row.docstatus) == 1 for row in linked_notes):
		frappe.throw(_("Schedule {0} already has a submitted Delivery Note. Create a separate schedule for any later delivery quantity.").format(schedule_name))


def _delivery_note_schedule_item_payloads(base_items, schedule_entries):
	"""Build one linked DN item per schedule without combining distinct schedule IDs."""
	base_by_so_item = {}
	for row in base_items or []:
		if row.so_detail in base_by_so_item:
			frappe.throw(_("ERPNext returned duplicate mapper rows for Sales Order Item {0}.").format(row.so_detail))
		base_by_so_item[row.so_detail] = row

	metadata_fields = {"name", "idx", "doctype", "parent", "parentfield", "parenttype",
		"docstatus", "owner", "creation", "modified", "modified_by", "_user_tags",
		"_comments", "_assign", "_liked_by", "__islocal", "__unsaved"}
	payloads = []
	for schedule, so_item, qty in schedule_entries:
		base = base_by_so_item.get(so_item.name)
		if not base:
			frappe.throw(_("ERPNext could not map Sales Order Item {0} for schedule {1}.").format(so_item.name, schedule.name))
		payload = {key: value for key, value in base.as_dict().items() if key not in metadata_fields}
		payload["qty"] = float(qty)
		payload[DN_SCHEDULE_FIELD] = schedule.name
		payloads.append(payload)
	return payloads


def _delivery_note_compatibility_key(so, schedule, so_item):
	"""A single draft DN may contain rows for one SO/date/warehouse group."""
	return so.name, str(schedule.delivery_date), so_item.warehouse


def _reset_logistics_confirmation(item):
	for fieldname in ("custom_logistics_reason", "custom_logistics_remarks", "custom_logistics_proposed_date"):
		if item.meta.has_field(fieldname):
			item.set(fieldname, None)
	if item.meta.has_field("custom_logistics_proposed_qty"):
		item.custom_logistics_proposed_qty = 0


def _reset_sales_confirmation(item):
	if item.meta.has_field("custom_sales_final_qty"):
		item.custom_sales_final_qty = 0
	if item.meta.has_field("custom_sales_move_date"):
		item.custom_sales_move_date = None
	if item.meta.has_field("custom_sales_remove"):
		item.custom_sales_remove = 0


def revise_draft_delivery_note_item(doc, item, new_qty, destination_date, remarks=None):
	"""Persist a Sales reduction and defer released demand as a new, source-linked schedule."""
	if not item.get(DN_SCHEDULE_FIELD) or doc.docstatus != 0 or doc.workflow_state != "Draft":
		frappe.throw(_("Only an unnumbered V2 Draft Delivery Note item can be revised."))
	if doc.get("custom_dr_number"):
		frappe.throw(_("A numbered Delivery Note cannot be revised."))
	if not destination_date:
		frappe.throw(_("Select a destination schedule date for the quantity difference."))
	source = frappe.get_doc("SO Delivery Schedule", item.get(DN_SCHEDULE_FIELD))
	so, so_item = _load_so_item(source.sales_order_item, lock=True)
	_require_sales_access(so, so_item, require_transact=True)
	_lock_schedules(so_item.name)
	source.reload()
	state = quantity_state(so_item.name, lock=True)
	precision = state["precision"]
	old_qty = Decimal(str(flt(item.qty, precision)))
	try:
		new_value = Decimal(str(new_qty))
	except (InvalidOperation, TypeError, ValueError):
		frappe.throw(_("Enter a valid quantity."))
	quantum = Decimal(1).scaleb(-precision)
	if not new_value.is_finite() or new_value < 0 or new_value.quantize(quantum) != new_value:
		frappe.throw(_("Quantity must be non-negative and use the item's allowed precision."))
	new_qty = new_value
	if new_qty == old_qty:
		frappe.throw(_("Enter a quantity different from the current Delivery Note quantity."))
	if new_qty > old_qty:
		frappe.throw(_("Sales cannot increase this DR line by selecting only a date. Obtain Logistics confirmation for the additional quantity first."))
	if new_qty == 0 and len(doc.items) == 1:
		frappe.throw(_("Moving the last item requires moving the whole Delivery Note."))
	from qcmc_logic.api.delivery_confirmation_service import _get_logistics_committed_qty
	committed = Decimal(str(flt(_get_logistics_committed_qty(item), precision)))
	if new_qty > committed:
		frappe.throw(_("Sales quantity cannot exceed Logistics commitment."))
	if not source.sales_order == so.name or source.sales_order_item != so_item.name:
		frappe.throw(_("Delivery Note item no longer matches its source schedule."))
	if item.get("delivery_date") and str(item.delivery_date) != str(source.delivery_date):
		frappe.throw(_("Delivery Note date no longer matches its linked schedule."))
	date = getdate(destination_date)
	if date < getdate(so.transaction_date) or date == getdate(source.delivery_date):
		frappe.throw(_("Choose a different valid destination schedule date."))
	if not remarks or not remarks.strip():
		frappe.throw(_("Enter a reason for the Sales quantity revision."))
	delta = old_qty - new_qty

	sp = "v2_sales_quantity_revision"
	frappe.db.savepoint(sp)
	previous = frappe.flags.get("delivery_schedule_service_write")
	try:
		frappe.flags.delivery_schedule_service_write = True
		if new_qty:
			item.qty = float(new_qty)
			item.custom_sales_final_qty = float(new_qty)
			item.custom_sales_move_date = source.delivery_date
			item.custom_sales_remove = 0
		else:
			doc.remove(item)
		doc.run_method("calculate_taxes_and_totals")
		doc.save(ignore_permissions=True)
		_transfer_to_new_schedule(source, so, so_item, delta, date,
			remarks.strip(), related_delivery_note=doc.name, related_dn_item=item.name,
			clear_source_confirmation=False,
			idempotency_key=f"sales-dr-revision:{doc.name}:{item.name}:{source.modified}:{new_qty}:{date}")
		source.reload()
		current_total = Decimal(str(source.current_total or 0))
		if source.logistics_committed_qty is not None:
			source.logistics_committed_qty = min(Decimal(str(source.logistics_committed_qty)), current_total)
		if source.final_qty is not None:
			source.final_qty = min(max(Decimal(0), Decimal(str(source.final_qty)) - delta), current_total)
		source.save(ignore_permissions=True)
		doc.add_comment("Info", _("Sales changed DR quantity from {0} to {1}; {2} was deferred to {3}.").format(old_qty, new_qty, delta, date))
	except Exception:
		frappe.db.rollback(save_point=sp)
		raise
	finally:
		frappe.flags.delivery_schedule_service_write = previous
	return {"saved": True, "delivery_note": doc.name, "deferred_qty": float(delta), "destination_date": str(date)}


def move_draft_delivery_note(doc, destination_date, remarks=None):
	"""Move an unnumbered schedule-linked Draft, preserving each promise cohort."""
	if doc.docstatus != 0 or doc.workflow_state != "Draft" or not doc.items:
		frappe.throw(_("Only an unnumbered Draft Delivery Note can be moved."))
	if doc.get("custom_dr_number"):
		frappe.throw(_("A numbered Delivery Note cannot be moved."))
	if not remarks or not remarks.strip():
		frappe.throw(_("Enter a reason for moving the Delivery Note."))
	if any(not row.get(DN_SCHEDULE_FIELD) for row in doc.items):
		frappe.throw(_("Every item on this Delivery Note must have a delivery schedule."))
	date = getdate(destination_date)
	schedule_docs = {row.get(DN_SCHEDULE_FIELD): frappe.get_doc("SO Delivery Schedule", row.get(DN_SCHEDULE_FIELD)) for row in doc.items}
	item_rows = {}
	for row in doc.items:
		schedule = schedule_docs[row.get(DN_SCHEDULE_FIELD)]
		if schedule.sales_order_item != row.so_detail or schedule.sales_order != row.against_sales_order:
			frappe.throw(_("Delivery Note schedule link does not match its Sales Order references."))
		item_rows.setdefault(schedule.name, []).append(row)
	so_item_names = sorted({schedule.sales_order_item for schedule in schedule_docs.values()})
	parents = sorted({schedule.sales_order for schedule in schedule_docs.values()})
	if parents:
		frappe.db.sql("SELECT name FROM `tabSales Order` WHERE name IN %(names)s ORDER BY name FOR UPDATE", {"names": tuple(parents)})
	so_by_item = {}
	for so_item_name in so_item_names:
		so, so_item = _load_so_item(so_item_name)
		_require_sales_access(so, so_item, require_transact=True)
		so_by_item[so_item_name] = (so, so_item)
	for so_item_name in so_item_names:
		_lock_schedules(so_item_name)
	schedule_docs = {name: frappe.get_doc("SO Delivery Schedule", name) for name in schedule_docs}
	for source_name, rows in item_rows.items():
		other_drafts = frappe.db.sql("""
			SELECT DISTINCT dn.name FROM `tabDelivery Note Item` dni
			JOIN `tabDelivery Note` dn ON dn.name = dni.parent
			WHERE dni.custom_so_delivery_schedule = %s AND dn.docstatus IN (0, 1) AND dn.name != %s
			LIMIT 1
		""", (source_name, doc.name))
		if other_drafts:
			frappe.throw(_("Move cannot change schedule confirmations while another active Delivery Note uses schedule {0}.").format(source_name))
	for schedule in schedule_docs.values():
		if date < getdate(so_by_item[schedule.sales_order_item][0].transaction_date):
			frappe.throw(_("Choose a valid destination date."))
	item_rows = {name: rows for name, rows in item_rows.items() if getdate(schedule_docs[name].delivery_date) != date}
	if not item_rows:
		frappe.throw(_("The Delivery Note is already scheduled for that date."))
	if doc.get("custom_dr_number"):
		frappe.throw(_("A Delivery Note with an assigned DR number cannot be moved."))
	dn_details = [row.name for row in doc.items]
	invoice_details = frappe.get_all("Sales Invoice Item", filters={"dn_detail": ["in", dn_details]}, pluck="parent")
	if invoice_details and frappe.get_all("Sales Invoice", filters={"name": ["in", sorted(set(invoice_details))], "docstatus": ["<", 2]}, pluck="name"):
		frappe.throw(_("A Delivery Note with an active invoice cannot be moved."))

	sp = "v2_whole_delivery_note_move"
	frappe.db.savepoint(sp)
	previous = frappe.flags.get("delivery_schedule_service_write")
	try:
		frappe.flags.delivery_schedule_service_write = True
		if doc.meta.has_field("posting_date"):
			doc.posting_date = date
		for source_name in sorted(item_rows):
			source = frappe.get_doc("SO Delivery Schedule", source_name)
			so, so_item = so_by_item[source.sales_order_item]
			rows = item_rows[source_name]
			qty = sum((Decimal(str(flt(row.qty, row.precision("qty")))) for row in rows), Decimal(0))
			if qty > Decimal(str(source.current_total if source.current_total is not None else source.planned_qty)):
				frappe.throw(_("Delivery Note allocation exceeds its source schedule."))
			dest_doc, tx = _transfer_to_new_schedule(source, so, so_item, qty, date,
				remarks.strip(),
				related_delivery_note=doc.name,
				related_dn_item=rows[0].name if len(rows) == 1 else None,
				allow_protected=False, reservation_qty=qty,
				idempotency_key=f"whole-dn-move:{doc.name}:{source.name}:{date}")
			for row in rows:
				row.set(DN_SCHEDULE_FIELD, dest_doc.name)
				if row.meta.has_field("delivery_date"):
					row.delivery_date = date
				_reset_logistics_confirmation(row)
				_reset_sales_confirmation(row)
		doc.run_method("calculate_taxes_and_totals")
		doc.save(ignore_permissions=True)
		doc.add_comment("Info", _("Whole Delivery Note moved to {0}; Logistics confirmation is required again. Reason: {1}").format(date, remarks.strip()))
	except Exception:
		frappe.db.rollback(save_point=sp)
		raise
	finally:
		frappe.flags.delivery_schedule_service_write = previous
	return {"saved": True, "delivery_note": doc.name, "delivery_date": str(date)}


def validate_delivery_note_item(doc, method=None):
	"""Keep new v2 DN links consistent; legacy items remain untouched."""
	previous_doc = getattr(doc, "_doc_before_save", None)
	if (previous_doc and previous_doc.get("workflow_state") == "Draft"
		and doc.get("workflow_state") == "To Deliver and Bill"):
		from qcmc_logic.api.delivery_printing_service import _validate_v2_release_transition

		_validate_v2_release_transition(doc)
	current_by_schedule = {}
	for row in doc.items:
		schedule_name = row.get(DN_SCHEDULE_FIELD)
		if not schedule_name:
			continue
		if doc.is_return:
			# Preserve ERPNext's return links, but returns do not consume/reopen the
			# operational plan or attach a forward delivery allocation.
			row.set(DN_SCHEDULE_FIELD, None)
			continue
		schedule = frappe.get_doc("SO Delivery Schedule", schedule_name)
		if schedule.sales_order_item != row.so_detail or schedule.sales_order != row.against_sales_order:
			frappe.throw(_("Delivery Note schedule must match its Sales Order and Sales Order Item references."))
		if schedule.item_code != row.item_code or schedule.warehouse != row.warehouse:
			frappe.throw(_("Delivery Note item and warehouse must match the linked schedule."))
		if row.get("delivery_date") and str(row.delivery_date) != str(schedule.delivery_date):
			frappe.throw(_("Delivery Note date must match the linked delivery schedule."))
		current_by_schedule[schedule.name] = current_by_schedule.get(schedule.name, Decimal(0)) + Decimal(str(flt(row.qty, row.precision("qty"))))
	if current_by_schedule:
		_validate_delivery_note_schedule_allocations(doc, current_by_schedule)


def _validate_delivery_note_schedule_allocations(doc, current_by_schedule):
	"""Serialize reservations per SO, then validate submitted + other drafts + this DN."""
	requested_names = tuple(sorted(current_by_schedule))
	rows = frappe.get_all("SO Delivery Schedule", filters={"name": ["in", requested_names]},
		fields=["name", "sales_order", "sales_order_item", "original_qty", "quantity_changes",
		"current_total", "planned_qty", "history_status"], order_by="name asc")
	if len(rows) != len(requested_names):
		frappe.throw(_("One or more delivery schedules no longer exist."))
	so_names = sorted({row.sales_order for row in rows})
	item_names = tuple(sorted({row.sales_order_item for row in rows}))
	# Parent-row locks serialize concurrent drafts even when they target different schedules
	# on the same SO Item. Schedule locks then stabilize each committed Total.
	for so_name in so_names:
		frappe.db.sql("SELECT name FROM `tabSales Order` WHERE name = %s FOR UPDATE", so_name)
	rows = frappe.get_all("SO Delivery Schedule", filters={"sales_order_item": ["in", item_names]},
		fields=["name", "sales_order", "sales_order_item", "original_qty", "quantity_changes",
		"current_total", "planned_qty", "history_status"], order_by="name asc")
	schedule_names = tuple(row.name for row in rows)
	frappe.db.sql("SELECT name FROM `tabSO Delivery Schedule` WHERE name IN %(names)s ORDER BY name FOR UPDATE",
		{"names": schedule_names})
	rows = frappe.get_all("SO Delivery Schedule", filters={"name": ["in", schedule_names]},
		fields=["name", "sales_order", "sales_order_item", "original_qty", "quantity_changes",
		"current_total", "planned_qty", "history_status"], order_by="name asc")
	if any(row.history_status != "Verified" for row in rows):
		frappe.throw(_("Reconcile historical schedules before allocating Delivery Note quantities."))
	dn_name = doc.name or ""
	allocations = frappe.db.sql("""
		SELECT dni.custom_so_delivery_schedule AS schedule, dn.docstatus, SUM(dni.qty) AS qty
		FROM `tabDelivery Note Item` dni JOIN `tabDelivery Note` dn ON dn.name = dni.parent
		WHERE dni.custom_so_delivery_schedule IN %(names)s AND dn.docstatus IN (0, 1)
		  AND dn.name != %(dn)s
		GROUP BY dni.custom_so_delivery_schedule, dn.docstatus
	""", {"names": schedule_names, "dn": dn_name}, as_dict=True)
	by_schedule = {name: {"submitted": Decimal(0), "draft": Decimal(0)} for name in schedule_names}
	for allocation in allocations:
		bucket = "submitted" if int(allocation.docstatus) == 1 else "draft"
		by_schedule[allocation.schedule][bucket] += Decimal(str(allocation.qty or 0))
	item_precision = {}
	for row in rows:
		current_qty = current_by_schedule.get(row.name, Decimal(0))
		if row.sales_order_item not in item_precision:
			item_precision[row.sales_order_item] = frappe.get_doc("Sales Order Item", row.sales_order_item).precision("qty")
		try:
			validate_schedule_allocation(row.current_total,
				by_schedule[row.name]["submitted"], by_schedule[row.name]["draft"],
				current_qty, item_precision[row.sales_order_item])
		except frappe.ValidationError:
			frappe.throw(_("Submitted and draft Delivery Note quantities exceed schedule {0} Total.").format(row.name))
	_validate_sales_order_item_conservation(rows, doc)


def _validate_sales_order_item_conservation(schedule_rows, doc):
	"""A schedule-linked DN remains within its SO Item's demand, including unlinked fulfillment."""
	items = sorted({row.sales_order_item for row in schedule_rows})
	for item_name in items:
		parent, ordered_qty = frappe.db.get_value("Sales Order Item", item_name, ["parent", "qty"])
		if not parent:
			frappe.throw(_("Scheduled Sales Order Item no longer exists."))
		so = frappe.get_doc("Sales Order", parent)
		item = next((row for row in so.items if row.name == item_name), None)
		if not item:
			frappe.throw(_("Scheduled Sales Order Item no longer exists."))
		precision = item.precision("qty")
		current_linked_qty = sum((Decimal(str(row.qty or 0)) for row in doc.items
			if row.so_detail == item_name and row.get(DN_SCHEDULE_FIELD) and not doc.is_return), Decimal(0))
		current_unlinked_qty = sum((Decimal(str(row.qty or 0)) for row in doc.items
			if row.so_detail == item_name and not row.get(DN_SCHEDULE_FIELD) and not doc.is_return), Decimal(0)) \
			if int(doc.docstatus or 0) == 1 else Decimal(0)
		schedule_rows_for_item = frappe.get_all("SO Delivery Schedule", filters={"sales_order_item": item_name},
			fields=["name", "original_qty", "quantity_changes", "current_total", "planned_qty", "history_status"])
		if any(row.history_status != "Verified" for row in schedule_rows_for_item):
			frappe.throw(_("Reconcile historical schedules before allocating Delivery Note quantities."))
		scheduled_total = sum((Decimal(str(row.current_total or 0)) for row in schedule_rows_for_item), Decimal(0))
		delivery_totals = frappe.db.sql("""
			SELECT COALESCE(SUM(dni.qty), 0) AS submitted_qty,
				COALESCE(SUM(CASE WHEN dni.custom_so_delivery_schedule IS NOT NULL AND dni.custom_so_delivery_schedule != ''
					THEN dni.qty ELSE 0 END), 0) AS linked_qty
			FROM `tabDelivery Note Item` dni JOIN `tabDelivery Note` dn ON dn.name = dni.parent
			WHERE dni.against_sales_order = %s AND dni.so_detail = %s AND dn.docstatus = 1 AND IFNULL(dn.is_return, 0) = 0
			  AND dn.name != %s
		""", (parent, item_name, doc.name or ""), as_dict=True)[0]
		balance = calculate_so_schedule_balance(ordered_qty, scheduled_total,
			Decimal(str(delivery_totals.submitted_qty or 0)) + current_linked_qty + current_unlinked_qty,
			Decimal(str(delivery_totals.linked_qty or 0)) + current_linked_qty, precision)
		if balance["unscheduled_qty"] < 0:
			frappe.throw(_("Schedules and unlinked fulfillment exceed Sales Order Item {0} quantity.").format(item_name))


def on_delivery_note_submit(doc, method=None):
	"""DN fulfillment is derived from submitted DN Items; it never mutates schedule Total."""
	return


def on_delivery_note_cancel(doc, method=None):
	"""Cancellation removes delivered quantity from derived fulfillment; Total is unchanged."""
	return


def _schedule_delta(schedule_name, delta, reason):
	"""Compatibility no-op: DN state must not change committed Total."""
	return
