import json
import uuid
from decimal import Decimal, InvalidOperation

import frappe
from frappe.utils import get_time, getdate, now_datetime

from qcmc_logic.api.stock_entry_scanner import (
	ScannerAPIError, _putaway_allocations, _resolve_storage_location,
	_split_finished_rows, _validate_override_location,
)
from qcmc_logic.api.warehouse_handover import _batch_response, _get_batch, _source_stock_entry
from qcmc_logic.api.warehouse_workflow import (
	WorkflowError, active_employee, authenticated_user, begin_request,
	error_response, finish_request, require_role,
)
from qcmc_logic.overrides.putaway_rule_dimension import (
	get_available_dimension_putaway_capacity,
)
from qcmc_logic.utils import ensure_scanner_warehouse_access


TRANSACTION_TYPES = {"Stock Entry", "Warehouse Transfer", "Warehouse Receiving Report", "Delivery Note", "Sales Invoice"}


def _decimal(value, positive=False):
	try:
		value = Decimal(str(value).replace(",", ""))
	except (InvalidOperation, TypeError, ValueError):
		raise WorkflowError("INVALID_QUANTITY", "Quantity must be numeric.")
	if not value.is_finite() or value < 0 or (positive and value <= 0):
		raise WorkflowError("INVALID_QUANTITY", "Quantity must be greater than zero." if positive else "Quantity must be non-negative.")
	return value


def _audit(event_type, allocation, row=None, request_id=None, reason=None, device_id=None, **extra):
	handover = frappe.get_doc("Scanner Warehouse Handover", allocation.handover)
	data = {
		"doctype": "Warehouse Workflow Audit", "event_id": str(uuid.uuid4()),
		"event_type": event_type, "handover": handover.name,
		"warehouse_allocation": allocation.name, "allocation_id": row.allocation_id if row else "",
		"source_doctype": row.source_doctype if row else "",
		"source_document": row.source_document if row else "", "source_row": row.source_row if row else "",
		"item_code": row.item_code if row else "", "original_quantity": row.original_qty if row else 0,
		"actual_quantity": row.actual_qty if row else 0,
		"stock_uom": row.stock_uom if row else "", "suggested_location": row.suggested_location if row else "",
		"actual_location": row.actual_location if row else "", "warehouse_man": handover.warehouse_man,
		"checker": handover.checker_employee, "assign_checker": handover.checker,
		"picker": allocation.picker, "device_id": device_id or allocation.device_id,
		"event_timestamp": now_datetime(), "reason": reason, "request_id": request_id,
	}
	data.update(extra)
	frappe.get_doc(data).insert(ignore_permissions=True)


def _load_allocation(name, user, mutate=True, allow_closed=False):
	if not name or not frappe.db.exists("Warehouse Allocation", name):
		raise WorkflowError("ALLOCATION_NOT_FOUND", "Warehouse Allocation was not found.")
	doc = frappe.get_doc("Warehouse Allocation", name)
	if not allow_closed and (doc.status in {"Completed", "Cancelled"} or doc.docstatus == 2):
		raise WorkflowError("ALLOCATION_INCOMPLETE", "Warehouse Allocation is no longer open.")
	try:
		ensure_scanner_warehouse_access(user, [doc.warehouse], require_transact=mutate)
	except frappe.PermissionError:
		raise WorkflowError("WAREHOUSE_PERMISSION_DENIED", "Warehouse permission denied.", status=403)
	return doc


def _row(doc, allocation_id):
	row = next((row for row in doc.locations if row.allocation_id == str(allocation_id or "")), None)
	if not row:
		raise WorkflowError("ALLOCATION_NOT_FOUND", "The allocation row was not found.")
	return row


def _source_key(row):
	return (row.source_doctype, row.source_document, row.source_row, row.item_code, row.stock_uom)


def _allocated_quantity(row):
	if row.status == "VERIFIED":
		return _decimal(row.actual_qty)
	return _decimal(row.suggested_qty or row.actual_qty or 0)


def _required_quantities(doc):
	"""Return authoritative stock quantities for every exact source item row."""
	required = {}
	for row in doc.locations:
		key = _source_key(row)
		if key in required:
			continue
		if row.source_doctype != "Stock Entry":
			required[key] = sum(_decimal(r.original_qty) for r in doc.locations if _source_key(r) == key)
			continue
		source = frappe.get_doc("Stock Entry", row.source_document)
		source_row = next((item for item in source.items if item.name == row.source_row), None)
		if not source_row or source_row.item_code != row.item_code or source_row.stock_uom != row.stock_uom:
			raise WorkflowError("SOURCE_DOCUMENT_CHANGED", "The source Stock Entry row no longer matches this allocation.")
		required[key] = _decimal(source_row.transfer_qty or source_row.qty * (source_row.conversion_factor or 1))
	return required


def _quantity_state(doc):
	required = _required_quantities(doc)
	allocated = {key: Decimal("0") for key in required}
	for row in doc.locations:
		allocated[_source_key(row)] = allocated.get(_source_key(row), Decimal("0")) + _allocated_quantity(row)
	remaining = {key: max(quantity - allocated.get(key, Decimal("0")), Decimal("0")) for key, quantity in required.items()}
	return required, allocated, remaining


def _row_response(row, required, target_warehouse):
	allocated = _allocated_quantity(row)
	return {
		"allocation_id": row.allocation_id, "source_doctype": row.source_doctype,
		"source_document": row.source_document, "source_row": row.source_row,
		"item_code": row.item_code,
		"item_name": frappe.db.get_value("Item", row.item_code, "item_name") or row.item_code,
		"stock_uom": row.stock_uom, "required_quantity": required,
		"original_quantity": row.original_qty, "suggested_quantity": row.suggested_qty,
		"actual_quantity": row.actual_qty, "allocated_quantity": allocated,
		"suggested_location": row.suggested_location, "actual_location": row.actual_location or "",
		"target_warehouse": target_warehouse, "priority": row.priority,
		"status": row.status, "scanner_id": row.scanner_id or "",
		"user_id": row.user or "", "user_full_name": row.user_full_name or "",
	}


def _response(doc, selected_row=None):
	required, allocated, remaining = _quantity_state(doc)
	rows = [_row_response(row, required[_source_key(row)], doc.warehouse) for row in doc.locations]
	response = {
		"success": True, "warehouse_allocation": doc.name, "docstatus": doc.docstatus,
		"status": doc.status, "batch_id": doc.handover, "checker": doc.checker,
		"picker": doc.picker, "required_quantity": sum(required.values(), Decimal("0")),
		"allocated_quantity": sum(allocated.values(), Decimal("0")),
		"remaining_unallocated_quantity": sum(remaining.values(), Decimal("0")),
		"rows": rows, "allocations": rows,
	}
	if selected_row:
		response["row"] = _row_response(selected_row, required[_source_key(selected_row)], doc.warehouse)
	return response


def _lock_and_reload(name, user):
	frappe.db.sql("select name from `tabWarehouse Allocation` where name=%s for update", name)
	return _load_allocation(name, user)


def _committed_location_quantities(item_code, warehouse, exclude_allocation=None, exclude_stock_entry=None):
	"""Return location occupancy recorded by Warehouse Allocation plus draft reservations.

	Submitted Stock Entries are created before putaway and therefore do not carry the
	final physical Storage Location. A completed Warehouse Allocation remains the
	authoritative location occupancy and must continue consuming capacity.
	"""
	reserved = {}
	allocation_rows = frappe.db.sql(
		"""
		select case when wal.status = 'VERIFIED'
			then wal.actual_location else wal.suggested_location end as location,
			sum(case when wal.status = 'VERIFIED'
				then wal.actual_qty else wal.suggested_qty end) as qty
		from `tabWarehouse Allocation Location` wal
		inner join `tabWarehouse Allocation` wa on wa.name = wal.parent
		where wa.docstatus < 2 and wa.status != 'Cancelled'
			and wal.item_code = %s and wa.warehouse = %s
			and (%s = '' or wa.name != %s)
		group by location
		""",
		(item_code, warehouse, exclude_allocation or "", exclude_allocation or ""),
		as_dict=True,
	)
	for row in allocation_rows:
		if row.location:
			reserved[row.location] = float(_decimal(row.qty))

	transfer_rows = frappe.db.sql(
		"""
		select location, sum(qty) as qty from (
			select target_location as location, quantity as qty
			from `tabLocation Transfer`
			where docstatus = 1 and item_code = %s and warehouse = %s
			union all
			select source_location as location, -quantity as qty
			from `tabLocation Transfer`
			where docstatus = 1 and item_code = %s and warehouse = %s
		) movements
		group by location
		""",
		(item_code, warehouse, item_code, warehouse),
		as_dict=True,
	)
	for row in transfer_rows:
		if row.location:
			reserved[row.location] = max(
				reserved.get(row.location, 0) + float(Decimal(str(row.qty or 0))), 0,
			)
	count_rows = frappe.db.sql(
		"""
		select coalesce(nullif(pcr.location, ''), pcr.inventory_location) as location,
			sum(pcr.variance) as qty
		from `tabQCMC Physical Count Result` pcr
		inner join `tabStock Reconciliation` sr on sr.name = pcr.parent
		where sr.docstatus = 1 and sr.custom_physical_count = 1
			and pcr.item_code = %s and pcr.warehouse = %s
		group by location
		""",
		(item_code, warehouse), as_dict=True,
	)
	for row in count_rows:
		if row.location:
			reserved[row.location] = max(
				reserved.get(row.location, 0) + float(Decimal(str(row.qty or 0))), 0,
			)

	draft_rows = frappe.db.sql(
		"""
		select coalesce(nullif(sed.custom_actual_storage_location, ''),
			nullif(sed.custom_recommended_storage_location, '')) as location,
			sum(sed.transfer_qty) as qty
		from `tabStock Entry Detail` sed
		inner join `tabStock Entry` se on se.name = sed.parent
		where se.docstatus = 0 and sed.item_code = %s and sed.t_warehouse = %s
			and (%s = '' or se.name != %s)
			and coalesce(nullif(sed.custom_actual_storage_location, ''),
				nullif(sed.custom_recommended_storage_location, '')) is not null
		group by location
		""",
		(item_code, warehouse, exclude_stock_entry or "", exclude_stock_entry or ""),
		as_dict=True,
	)
	for row in draft_rows:
		if row.location:
			reserved[row.location] = reserved.get(row.location, 0) + float(_decimal(row.qty))
	return reserved


def _live_location_capacity(doc, row, location):
	"""Return live capacity for every scanned regular location.

	Only an unrestricted, zero-capacity Open Area is unlimited. Every other
	location must have an active Putaway Rule for this item and warehouse.
	"""
	rule_name = _putaway_rule_for_location(row.item_code, doc.company, doc.warehouse, location.name)
	if not rule_name:
		if (
			location.location_type == "Open Area"
			and not str(location.custom_restricted_item or "").strip()
			and _decimal(location.custom_storage_capacity) <= 0
		):
			return None, ""
		raise WorkflowError(
			"LOCATION_NOT_ALLOWED",
			f"Storage Location '{location.name}' has no active Putaway Rule for {row.item_code}.",
		)

	available = Decimal(str(get_available_dimension_putaway_capacity(rule_name, item_code=row.item_code)))
	reserved = _committed_location_quantities(
		row.item_code, doc.warehouse, exclude_allocation=doc.name,
		exclude_stock_entry=row.source_document,
	)
	available -= _decimal(reserved.get(location.name, 0))
	for other in doc.locations:
		if other.allocation_id == row.allocation_id or other.item_code != row.item_code:
			continue
		other_location = other.actual_location if other.status == "VERIFIED" else other.suggested_location
		if other_location == location.name:
			available -= _allocated_quantity(other)
	return max(available, Decimal("0")), rule_name


def _putaway_rule_for_location(item_code, company, warehouse, location):
	has_no_item_field = frappe.get_meta("Putaway Rule").has_field("custom_no_item_restriction")
	fields = ["name", "item_code", "priority"]
	if has_no_item_field:
		fields.append("custom_no_item_restriction")
	rules = frappe.get_all(
		"Putaway Rule",
		filters={"company": company, "warehouse": warehouse, "location": location, "disable": 0},
		or_filters=[
			{"item_code": item_code},
			{"custom_no_item_restriction": 1},
		] if has_no_item_field else {"item_code": item_code},
		fields=fields,
		order_by="priority asc, creation asc",
	)
	rules = sorted(
		rules,
		key=lambda rule: (
			0 if str(rule.get("item_code") or "").strip() == str(item_code or "").strip() else 1,
			rule.priority or 0,
			rule.name,
		),
	)
	return rules[0].name if rules else ""


def _live_rule_capacity(doc, row, location):
	"""Backward-compatible capacity-only wrapper used by pending refresh."""
	available, _rule_name = _live_location_capacity(doc, row, location)
	return available


def _reallocate_remainder(doc, changed_row, exclude_changed_location=True):
	"""Append Put Away suggestions for the exact source-row shortfall."""
	required, allocated, remaining = _quantity_state(doc)
	key = _source_key(changed_row)
	if allocated[key] > required[key]:
		raise WorkflowError(
			"ALLOCATION_QUANTITY_EXCEEDED",
			"Allocated quantity cannot exceed the required Production quantity.",
		)
	shortfall = remaining[key]
	if shortfall <= 0 or changed_row.source_doctype != "Stock Entry":
		return shortfall

	source = frappe.get_doc("Stock Entry", changed_row.source_document)
	source_row = next(row for row in source.items if row.name == changed_row.source_row)
	allocation_row = frappe._dict(source_row.as_dict() if callable(getattr(source_row, "as_dict", None)) else source_row)
	conversion_factor = _decimal(source_row.conversion_factor or 1)
	allocation_row.transfer_qty = shortfall
	allocation_row.qty = shortfall / conversion_factor
	allocation_row.custom_putaway_allocation_id = ""
	allocation_row.custom_recommended_storage_location = ""
	allocation_row.custom_actual_storage_location = ""

	reserved_capacity = _committed_location_quantities(
		changed_row.item_code, doc.warehouse, exclude_allocation=doc.name,
		exclude_stock_entry=changed_row.source_document,
	)
	for row in doc.locations:
		if row.item_code != changed_row.item_code or row.stock_uom != changed_row.stock_uom:
			continue
		location = row.actual_location if row.status == "VERIFIED" else row.suggested_location
		if location:
			reserved_capacity[location] = float(_decimal(reserved_capacity.get(location, 0)) + _allocated_quantity(row))

	excluded_locations = (
		{changed_row.actual_location or changed_row.suggested_location}
		if exclude_changed_location else set()
	)
	for suggested in _putaway_allocations(
		source, allocation_row, reserved_capacity=reserved_capacity,
		excluded_locations=excluded_locations,
		preferred_location=changed_row.actual_location or changed_row.suggested_location,
	):
		doc.append("locations", {
			"allocation_id": str(uuid.uuid4()), "source_doctype": changed_row.source_doctype,
			"source_document": changed_row.source_document, "source_row": changed_row.source_row,
			"item_code": changed_row.item_code, "stock_uom": changed_row.stock_uom,
			"original_qty": suggested["stock_quantity"],
			"suggested_location": suggested["inventory_location_id"],
			"suggested_qty": suggested["stock_quantity"], "actual_qty": 0,
			"priority": suggested.get("priority") or 0,
			"putaway_rule": suggested.get("putaway_rule") or "",
			"status": "PENDING_VERIFICATION",
		})
	return _quantity_state(doc)[2][key]


def _refresh_stale_pending_suggestions(doc):
	"""Replace pending recommendations whose live capacity is no longer sufficient."""
	changed = False
	for row in list(doc.locations):
		if row.status == "VERIFIED" or not row.putaway_rule or not row.suggested_location:
			continue
		location = _resolve_storage_location(row.suggested_location, require_leaf=True, allow_legacy_code=True)
		available = _live_rule_capacity(doc, row, location)
		if available is None or _allocated_quantity(row) <= available:
			continue

		row.suggested_qty = 0
		row.actual_qty = 0
		row.actual_location = ""
		row.status = "PENDING_VERIFICATION"
		_reallocate_remainder(doc, row, exclude_changed_location=False)
		doc.remove(row)
		changed = True

	changed = _merge_pending_location_rows(doc) or changed
	if changed:
		doc.locations.sort(key=lambda row: (row.priority, _natural_key(row.suggested_location)))
		_refresh_item_progress(doc)
		doc.save(ignore_permissions=True)
	return changed


def _merge_pending_location_rows(doc):
	"""Combine unverified rows that point to the same source and Storage Location."""
	merged = False
	rows_by_key = {}
	for row in list(doc.locations):
		if row.status == "VERIFIED" or row.actual_location:
			continue
		key = (
			row.source_doctype, row.source_document, row.source_row,
			row.item_code, row.stock_uom, row.suggested_location,
			row.putaway_rule or "", row.status,
		)
		primary = rows_by_key.get(key)
		if not primary:
			rows_by_key[key] = row
			continue
		primary.original_qty = _decimal(primary.original_qty) + _decimal(row.original_qty)
		primary.suggested_qty = _decimal(primary.suggested_qty) + _decimal(row.suggested_qty)
		primary.actual_qty = _decimal(primary.actual_qty) + _decimal(row.actual_qty)
		doc.remove(row)
		merged = True
	return merged


def _populate_summary_tables(allocation):
	"""Build the ERP-facing reference and item tables from scanner allocations."""
	allocation.set("references", [])
	allocation.set("items", [])

	references = {}
	item_totals = {}
	for row in allocation.locations:
		quantity = _decimal(row.original_qty)
		reference_key = (row.source_doctype, row.source_document, row.source_row)
		reference = references.setdefault(reference_key, {
			"reference_doctype": row.source_doctype,
			"reference_name": row.source_document,
			"item_code": row.item_code,
			"qty": Decimal("0"),
			"uom": row.stock_uom,
		})
		reference["qty"] += quantity

		item_key = (row.item_code, row.stock_uom)
		item_totals[item_key] = item_totals.get(item_key, Decimal("0")) + quantity

	for reference in references.values():
		allocation.append("references", reference)
	for (item_code, uom), quantity in item_totals.items():
		allocation.append("items", {
			"item_code": item_code,
			"uom": uom,
			"qty": quantity,
			"putaway_qty": 0,
			"remaining_qty": quantity,
		})
	_refresh_item_progress(allocation)


def _refresh_item_progress(allocation):
	"""Reflect only physically verified location quantities in Item Details."""
	verified = {}
	for row in allocation.locations:
		if row.status == "VERIFIED" and row.actual_location:
			key = (row.item_code, row.stock_uom)
			verified[key] = verified.get(key, Decimal("0")) + _decimal(row.actual_qty)

	for item in allocation.items:
		allocated = verified.get((item.item_code, item.uom), Decimal("0"))
		total = _decimal(item.qty)
		item.putaway_qty = allocated
		item.remaining_qty = max(total - allocated, Decimal("0"))


def backfill_allocation_summary(name):
	"""Repair summary tables on allocations created by older scanner code."""
	allocation = frappe.get_doc("Warehouse Allocation", name)
	_populate_summary_tables(allocation)
	allocation.save(ignore_permissions=True)
	frappe.db.commit()
	return {"name": allocation.name, "references": len(allocation.references), "items": len(allocation.items)}


@frappe.whitelist(allow_guest=True)
def create_draft(batch_id, handover_token, transaction_type, warehouse, posting_date, request_id,
	posting_time=None, additional_details=None, device_id=None, mobile_token=None):
	try:
		user = authenticated_user(mobile_token)
		picker = active_employee(user)
		require_role(user, "Warehouse Picker", "PICKER_NOT_AUTHORIZED")
		if transaction_type not in TRANSACTION_TYPES:
			raise WorkflowError("INVALID_TRANSACTION_TYPE", "The selected transaction type is not supported.")
		request = begin_request("warehouse_allocation.create_draft", request_id, {
			"batch_id": batch_id, "transaction_type": transaction_type, "warehouse": warehouse,
			"posting_date": posting_date, "posting_time": posting_time or "", "additional_details": additional_details or {},
		}, user)
		if request.replay is not None:
			return request.replay
		batch = _get_batch(batch_id, user, token=handover_token, mutate=True)
		existing_allocation = frappe.db.get_value("Warehouse Allocation", {"handover": batch.name}, "name")
		if existing_allocation:
			allocation = _load_allocation(existing_allocation, user, mutate=False)
			response = _response(allocation)
			response.update({"existing_allocation": True, "duplicate_request": True})
			return finish_request(request, response)
		if batch.status != "CHECKED":
			raise WorkflowError("HANDOVER_NOT_CHECKED", "The handover must be CHECKED before allocation.")
		if not batch.get("stock_entries_submitted") or not batch.checker:
			raise WorkflowError("HANDOVER_NOT_CHECKED", "Checker Verification and Stock Entry submission are required before allocation.")
		try:
			ensure_scanner_warehouse_access(user, [warehouse], require_transact=True)
		except frappe.PermissionError:
			raise WorkflowError("WAREHOUSE_PERMISSION_DENIED", "Warehouse permission denied.", status=403)
		allocation = frappe.get_doc({
			"doctype": "Warehouse Allocation", "company": batch.company, "warehouse": warehouse,
			"posting_date": getdate(posting_date), "posting_time": get_time(posting_time) if posting_time else None,
			"status": "Draft", "handover": batch.name,
			"transaction_type": transaction_type, "picker": picker.name, "checker": batch.checker_employee,
			"device_id": device_id,
		})
		reserved_by_item = {}
		shared_reserved_capacity = {}
		for source in batch.source_stock_entries:
			stock_entry = _source_stock_entry(source.stock_entry, user, mutate=False, docstatus=1)
			if str(stock_entry.modified) != str(source.source_modified):
				raise WorkflowError("SOURCE_DOCUMENT_CHANGED", f"Stock Entry '{stock_entry.name}' changed after Checker verification.")
			stock_row = next((row for row in stock_entry.items if row.name == source.stock_entry_row), None)
			if not stock_row:
				raise WorkflowError("SOURCE_DOCUMENT_CHANGED", "A checked source row no longer exists.")
			if stock_row.t_warehouse != warehouse:
				raise WorkflowError("WAREHOUSE_PERMISSION_DENIED", f"Source row warehouse is {stock_row.t_warehouse}, not {warehouse}.")
			reservation_key = (stock_row.item_code, stock_row.stock_uom, stock_row.t_warehouse)
			reserved_capacity = reserved_by_item.setdefault(
				reservation_key,
				_committed_location_quantities(
					stock_row.item_code, stock_row.t_warehouse,
					exclude_stock_entry=stock_entry.name,
				),
			)
			for suggested in _putaway_allocations(
				stock_entry,
				stock_row,
				reserved_capacity=reserved_capacity,
				shared_reserved_capacity=shared_reserved_capacity,
			):
				allocation.append("locations", {
					"allocation_id": str(uuid.uuid4()), "source_doctype": "Stock Entry",
					"source_document": stock_entry.name, "source_row": stock_row.name,
					"item_code": stock_row.item_code, "stock_uom": stock_row.stock_uom,
					"original_qty": suggested["stock_quantity"],
					"suggested_location": suggested["inventory_location_id"],
					"suggested_qty": suggested["stock_quantity"], "actual_qty": 0,
					"priority": suggested.get("priority") or 0, "putaway_rule": suggested.get("putaway_rule") or "",
					"status": "PENDING_VERIFICATION",
				})
		if not allocation.locations:
			raise WorkflowError("INSUFFICIENT_PUTAWAY_CAPACITY", "No Putaway allocation could be created.")
		_merge_pending_location_rows(allocation)
		allocation.locations.sort(key=lambda row: (row.priority, _natural_key(row.suggested_location)))
		_populate_summary_tables(allocation)
		allocation.insert(ignore_permissions=True)
		batch.picker = picker.name
		batch.status = "ALLOCATION_CREATED"
		batch.allocation_created_at = now_datetime()
		batch.save(ignore_permissions=True)
		_audit("ALLOCATION_CREATED", allocation, request_id=request.name, device_id=device_id)
		return finish_request(request, _response(allocation))
	except WorkflowError as exc:
		return error_response(exc)
	except ScannerAPIError as exc:
		return error_response(WorkflowError(exc.code, str(exc), exc.details))
	except Exception as exc:
		frappe.log_error(frappe.get_traceback(), "warehouse_allocation.create_draft")
		return error_response(WorkflowError("ERP_VALIDATION_FAILED", str(exc)))


def _natural_key(value):
	import re
	return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", str(value or ""))]


def _validate_location(doc, row, location_id, quantity):
	try:
		location = _resolve_storage_location(location_id, require_leaf=True)
	except ScannerAPIError as exc:
		mapping = {"LOCATION_NOT_FOUND": "LOCATION_NOT_FOUND", "LOCATION_IS_GROUP": "LOCATION_IS_GROUP"}
		raise WorkflowError(mapping.get(exc.code, exc.code), str(exc), exc.details)
	if location.custom_warehouse != doc.warehouse:
		raise WorkflowError("LOCATION_WAREHOUSE_MISMATCH", f"Storage Location '{location.name}' is not in {doc.warehouse}.")
	allocation = {"item_code": row.item_code, "target_warehouse": doc.warehouse,
		"stock_quantity": quantity, "stock_uom": row.stock_uom}
	try:
		_validate_override_location(allocation, location)
	except ScannerAPIError as exc:
		raise WorkflowError(exc.code, str(exc), exc.details)
	return location


@frappe.whitelist(allow_guest=True)
def verify_location(warehouse_allocation, allocation_id, scanned_location_id, item_code,
	actual_quantity, transaction_id, device_id=None, timestamp=None, picker_id=None, mobile_token=None):
	savepoint_started = False
	try:
		user = authenticated_user(mobile_token)
		picker = active_employee(user)
		require_role(user, "Warehouse Picker", "PICKER_NOT_AUTHORIZED")
		request = begin_request("warehouse_allocation.verify_location", transaction_id, {
			"warehouse_allocation": warehouse_allocation, "allocation_id": allocation_id,
			"scanned_location_id": scanned_location_id, "item_code": item_code,
			"actual_quantity": actual_quantity, "device_id": device_id or "",
		}, user)
		if request.replay is not None:
			return request.replay
		frappe.db.savepoint("verify_allocation_location")
		savepoint_started = True
		doc = _lock_and_reload(warehouse_allocation, user)
		if doc.picker != picker.name and user != "Administrator":
			raise WorkflowError("PICKER_NOT_AUTHORIZED", "This allocation belongs to another Picker.", status=403)
		row = _row(doc, allocation_id)
		if row.item_code != item_code:
			raise WorkflowError("LOCATION_ITEM_MISMATCH", "The scanned item does not match this allocation.")
		quantity = _decimal(actual_quantity, positive=True)
		location = _validate_location(doc, row, scanned_location_id, quantity)
		live_capacity, scanned_rule = _live_location_capacity(doc, row, location)
		if live_capacity is not None and quantity > live_capacity:
			if location.name != row.suggested_location:
				raise WorkflowError(
					"LOCATION_CAPACITY_EXCEEDED",
					f"Storage Location '{location.name}' has only {live_capacity} {row.stock_uom} available and cannot receive {quantity} {row.stock_uom}.",
					{"storage_location": location.name, "available_capacity": live_capacity, "requested_quantity": quantity},
				)
			# The recommendation became stale after it was created. Preserve no
			# reservation at the full location and regenerate this exact source
			# quantity against the latest capacities.
			stale_row = row
			stale_row.suggested_qty = 0
			stale_row.actual_qty = 0
			stale_row.actual_location = ""
			stale_row.status = "PENDING_VERIFICATION"
			_reallocate_remainder(doc, stale_row)
			doc.remove(stale_row)
			doc.status = "In Progress"
			_refresh_item_progress(doc)
			doc.save(ignore_permissions=True)
			_audit(
				"LOCATION_REALLOCATED", doc, stale_row, request.name,
				reason="Live capacity changed before verification", device_id=device_id,
				details_json=json.dumps({"available_capacity": str(live_capacity)}),
			)
			response = _response(doc)
			response.update({
				"reallocated": True,
				"message": "The suggested location no longer has enough live capacity. ERPNext recalculated the allocation; verify the new suggestion.",
			})
			return finish_request(request, response)
		row.actual_location = location.name
		row.actual_qty = quantity
		row.putaway_rule = scanned_rule
		row.status = "VERIFIED"
		row.scanner_id = device_id
		row.user = user
		row.user_full_name = frappe.db.get_value("User", user, "full_name") or user
		row.scan_time = now_datetime()
		doc.status = "In Progress"
		remaining = _reallocate_remainder(doc, row)
		_refresh_item_progress(doc)
		doc.save(ignore_permissions=True)
		_audit("LOCATION_VERIFIED", doc, row, request.name, device_id=device_id)
		response = _response(doc, row)
		if remaining > 0:
			response["message"] = "The verified quantity was saved, but some quantity remains unallocated because no valid location has sufficient capacity."
		return finish_request(request, response)
	except WorkflowError as exc:
		if savepoint_started:
			frappe.db.rollback(save_point="verify_allocation_location")
		return error_response(exc)
	except Exception as exc:
		if savepoint_started:
			frappe.db.rollback(save_point="verify_allocation_location")
		return error_response(WorkflowError("ERP_VALIDATION_FAILED", str(exc)))


@frappe.whitelist(allow_guest=True)
def change_location(warehouse_allocation, allocation_id, new_location_id, actual_quantity,
	reason, transaction_id, device_id=None, mobile_token=None):
	savepoint_started = False
	try:
		if not str(reason or "").strip():
			raise WorkflowError("ERP_VALIDATION_FAILED", "A reason is required to change location.")
		user = authenticated_user(mobile_token)
		picker = active_employee(user)
		require_role(user, "Warehouse Picker", "PICKER_NOT_AUTHORIZED")
		request = begin_request("warehouse_allocation.change_location", transaction_id, {
			"warehouse_allocation": warehouse_allocation, "allocation_id": allocation_id,
			"new_location_id": new_location_id, "actual_quantity": actual_quantity, "reason": reason,
		}, user)
		if request.replay is not None:
			return request.replay
		frappe.db.savepoint("change_allocation_location")
		savepoint_started = True
		doc = _lock_and_reload(warehouse_allocation, user)
		if doc.picker != picker.name and user != "Administrator":
			raise WorkflowError("PICKER_NOT_AUTHORIZED", "This allocation belongs to another Picker.", status=403)
		row = _row(doc, allocation_id)
		quantity = _decimal(actual_quantity, positive=True)
		previous = row.actual_location or ""
		location = _validate_location(doc, row, new_location_id, quantity)
		live_capacity, scanned_rule = _live_location_capacity(doc, row, location)
		if live_capacity is not None and quantity > live_capacity:
			raise WorkflowError(
				"LOCATION_CAPACITY_EXCEEDED",
				f"Storage Location '{location.name}' has only {live_capacity} {row.stock_uom} available and cannot receive {quantity} {row.stock_uom}.",
				{"storage_location": location.name, "available_capacity": live_capacity, "requested_quantity": quantity},
			)
		row.actual_location, row.actual_qty, row.status = location.name, quantity, "VERIFIED"
		row.putaway_rule = scanned_rule
		row.scanner_id, row.user = device_id, user
		row.user_full_name = frappe.db.get_value("User", user, "full_name") or user
		row.scan_time = now_datetime()
		doc.status = "In Progress"
		_reallocate_remainder(doc, row)
		_refresh_item_progress(doc)
		doc.save(ignore_permissions=True)
		_audit("LOCATION_CHANGED", doc, row, request.name, reason, device_id,
			details_json=json.dumps({"previous_actual_location": previous}))
		return finish_request(request, _response(doc, row))
	except WorkflowError as exc:
		if savepoint_started:
			frappe.db.rollback(save_point="change_allocation_location")
		return error_response(exc)
	except Exception as exc:
		if savepoint_started:
			frappe.db.rollback(save_point="change_allocation_location")
		return error_response(WorkflowError("ERP_VALIDATION_FAILED", str(exc)))


@frappe.whitelist(allow_guest=True)
def adjust_quantity(warehouse_allocation, allocation_id, actual_quantity, reason,
	transaction_id, device_id=None, mobile_token=None):
	savepoint_started = False
	try:
		user = authenticated_user(mobile_token)
		picker = active_employee(user)
		require_role(user, "Warehouse Picker", "PICKER_NOT_AUTHORIZED")
		request = begin_request("warehouse_allocation.adjust_quantity", transaction_id, {
			"warehouse_allocation": warehouse_allocation, "allocation_id": allocation_id,
			"actual_quantity": actual_quantity, "reason": reason or "",
		}, user)
		if request.replay is not None:
			return request.replay
		frappe.db.savepoint("adjust_allocation_quantity")
		savepoint_started = True
		doc = _lock_and_reload(warehouse_allocation, user)
		if doc.picker != picker.name and user != "Administrator":
			raise WorkflowError("PICKER_NOT_AUTHORIZED", "This allocation belongs to another Picker.", status=403)
		row = _row(doc, allocation_id)
		quantity = _decimal(actual_quantity)
		previous = Decimal(str(row.actual_qty or row.suggested_qty or 0))
		if quantity != previous and not str(reason or "").strip():
			raise WorkflowError("ERP_VALIDATION_FAILED", "A reason is required when quantity changes.")
		row.actual_qty = quantity
		row.status = "VERIFIED" if row.actual_location and quantity > 0 else "PENDING_VERIFICATION"
		doc.status = "In Progress"
		_reallocate_remainder(doc, row)
		_refresh_item_progress(doc)
		doc.save(ignore_permissions=True)
		_audit("QUANTITY_ADJUSTED", doc, row, request.name, reason, device_id,
			details_json=json.dumps({"previous_actual_quantity": str(previous)}))
		return finish_request(request, _response(doc, row))
	except WorkflowError as exc:
		if savepoint_started:
			frappe.db.rollback(save_point="adjust_allocation_quantity")
		return error_response(exc)
	except Exception as exc:
		if savepoint_started:
			frappe.db.rollback(save_point="adjust_allocation_quantity")
		return error_response(WorkflowError("ERP_VALIDATION_FAILED", str(exc)))


@frappe.whitelist(allow_guest=True)
def get_allocation(warehouse_allocation, mobile_token=None):
	try:
		user = authenticated_user(mobile_token)
		doc = _load_allocation(warehouse_allocation, user, mutate=False, allow_closed=True)
		if doc.docstatus == 0 and doc.status not in {"Completed", "Cancelled"}:
			frappe.db.savepoint("refresh_allocation_capacity")
			doc = _lock_and_reload(warehouse_allocation, user)
			_refresh_stale_pending_suggestions(doc)
		return _response(doc)
	except WorkflowError as exc:
		return error_response(exc)
	except Exception as exc:
		return error_response(WorkflowError("ERP_VALIDATION_FAILED", str(exc)))


@frappe.whitelist(allow_guest=True)
def get_device_completed_history(device_id, mobile_token=None):
	"""Return permanent completed history belonging only to one scanner device."""
	try:
		user = authenticated_user(mobile_token)
		require_role(user, "Warehouse Picker", "PICKER_NOT_AUTHORIZED")
		device_id = str(device_id or "").strip()
		if not device_id:
			raise WorkflowError("DEVICE_ID_REQUIRED", "Scanner Device ID is required.")

		names = frappe.get_all(
			"Warehouse Allocation",
			filters={"device_id": device_id, "status": "Completed", "docstatus": 1},
			pluck="name",
			order_by="completed_at desc, modified desc",
		)
		history = []
		for name in names:
			doc = frappe.get_doc("Warehouse Allocation", name)
			try:
				ensure_scanner_warehouse_access(user, [doc.warehouse], require_transact=False)
			except frappe.PermissionError:
				continue
			entry = _response(doc)
			entry.update({
				"device_id": doc.device_id,
				"warehouse": doc.warehouse,
				"posting_date": doc.posting_date,
				"posting_time": doc.posting_time,
				"completed_at": doc.completed_at,
			})
			history.append(entry)
		return {
			"success": True,
			"device_id": device_id,
			"history": history,
			"completed_allocations": history,
			"count": len(history),
		}
	except WorkflowError as exc:
		return error_response(exc)
	except Exception as exc:
		frappe.log_error(frappe.get_traceback(), "warehouse_allocation.get_device_completed_history")
		return error_response(WorkflowError("ERP_VALIDATION_FAILED", str(exc)))


@frappe.whitelist(allow_guest=True)
def complete(warehouse_allocation, request_id, device_id=None, mobile_token=None):
	try:
		user = authenticated_user(mobile_token)
		picker = active_employee(user)
		require_role(user, "Warehouse Picker", "PICKER_NOT_AUTHORIZED")
		request = begin_request("warehouse_allocation.complete", request_id, {
			"warehouse_allocation": warehouse_allocation, "device_id": device_id or "",
		}, user)
		if request.replay is not None:
			return request.replay
		doc = _load_allocation(warehouse_allocation, user)
		if doc.picker != picker.name and user != "Administrator":
			raise WorkflowError("PICKER_NOT_AUTHORIZED", "This allocation belongs to another Picker.", status=403)
		pending = [row.allocation_id for row in doc.locations if row.status != "VERIFIED" or not row.actual_location]
		if pending:
			raise WorkflowError("ALLOCATION_INCOMPLETE", "Every allocation row must be physically verified.", {"allocation_ids": pending})
		required, allocated, remaining = _quantity_state(doc)
		overallocated = [key for key in required if allocated.get(key, Decimal("0")) > required[key]]
		if overallocated:
			raise WorkflowError(
				"ALLOCATION_QUANTITY_EXCEEDED",
				"Allocated quantity cannot exceed the required Production quantity.",
			)
		if any(remaining.values()) or any(allocated.get(key, Decimal("0")) != quantity for key, quantity in required.items()):
			raise WorkflowError(
				"ALLOCATION_INCOMPLETE",
				"Allocated quantities must exactly match every required source quantity before completion.",
				{"remaining_unallocated_quantity": sum(remaining.values(), Decimal("0"))},
			)
		by_source = {}
		for row in doc.locations:
			by_source.setdefault(row.source_document, []).append(row)
		for stock_entry_name, rows in by_source.items():
			stock_entry = _source_stock_entry(stock_entry_name, user, mutate=False, docstatus=1)
			batch = frappe.get_doc("Scanner Warehouse Handover", doc.handover)
			versions = {row.stock_entry_row: str(row.source_modified) for row in batch.source_stock_entries if row.stock_entry == stock_entry_name}
			if any(str(stock_entry.modified) != version for version in versions.values()):
				raise WorkflowError("SOURCE_DOCUMENT_CHANGED", f"Stock Entry '{stock_entry.name}' changed after Checker verification.")
		completion_device_id = str(device_id or doc.device_id or "").strip()
		if not completion_device_id:
			raise WorkflowError("DEVICE_ID_REQUIRED", "Scanner Device ID is required to complete this allocation.")
		doc.device_id = completion_device_id
		doc.status = "Completed"
		doc.completed_at = now_datetime()
		# Completing the scanner workflow is also the formal submission of the
		# Warehouse Allocation document. Source Stock Entries were already
		# submitted during Checker confirmation and remain immutable here.
		doc.flags.ignore_permissions = True
		doc.submit()
		batch = frappe.get_doc("Scanner Warehouse Handover", doc.handover)
		batch.status, batch.completed_at, batch.picker = "COMPLETED", now_datetime(), picker.name
		batch.save(ignore_permissions=True)
		_audit("ALLOCATION_COMPLETED", doc, request_id=request.name, device_id=device_id)
		response = _response(doc)
		response["source_documents"] = [{"stock_entry_id": name, "docstatus": 1, "status": "Submitted"} for name in by_source]
		return finish_request(request, response)
	except WorkflowError as exc:
		return error_response(exc)
	except Exception as exc:
		frappe.log_error(frappe.get_traceback(), "warehouse_allocation.complete")
		return error_response(WorkflowError("ERP_VALIDATION_FAILED", str(exc)))
