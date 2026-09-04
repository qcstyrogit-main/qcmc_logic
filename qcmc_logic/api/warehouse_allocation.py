import json
import uuid
from decimal import Decimal, InvalidOperation

import frappe
from frappe.utils import get_time, getdate, now_datetime

from qcmc_logic.api.stock_entry_scanner import (
	ScannerAPIError, _putaway_allocations, _resolve_storage_location,
	_split_finished_rows, _validate_override_location,
)
from qcmc_logic.api.warehouse_handover import _batch_response, _get_batch, _draft_stock_entry
from qcmc_logic.api.warehouse_workflow import (
	WorkflowError, active_employee, authenticated_user, begin_request,
	error_response, finish_request, require_role,
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


def _load_allocation(name, user, mutate=True):
	if not name or not frappe.db.exists("Warehouse Allocation", name):
		raise WorkflowError("ALLOCATION_NOT_FOUND", "Warehouse Allocation was not found.")
	doc = frappe.get_doc("Warehouse Allocation", name)
	if doc.status in {"Completed", "Cancelled"} or doc.docstatus == 2:
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


def _response(doc):
	return {
		"success": True, "warehouse_allocation": doc.name, "docstatus": doc.docstatus,
		"status": doc.status, "batch_id": doc.handover, "checker": doc.checker,
		"picker": doc.picker,
		"allocations": [{
			"allocation_id": row.allocation_id, "source_doctype": row.source_doctype,
			"source_document": row.source_document, "source_row": row.source_row,
			"item_code": row.item_code,
			"item_name": frappe.db.get_value("Item", row.item_code, "item_name") or row.item_code,
			"stock_uom": row.stock_uom, "original_quantity": row.original_qty,
			"allocated_quantity": row.actual_qty,
			"suggested_location": row.suggested_location, "actual_location": row.actual_location or "",
			"target_warehouse": doc.warehouse, "priority": row.priority,
			"status": row.status,
		} for row in doc.locations],
	}


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
		for source in batch.source_stock_entries:
			stock_entry = _draft_stock_entry(source.stock_entry, user, mutate=True)
			if str(stock_entry.modified) != str(source.source_modified):
				raise WorkflowError("SOURCE_DOCUMENT_CHANGED", f"Stock Entry '{stock_entry.name}' changed after Checker verification.")
			stock_row = next((row for row in stock_entry.items if row.name == source.stock_entry_row), None)
			if not stock_row:
				raise WorkflowError("SOURCE_DOCUMENT_CHANGED", "A checked source row no longer exists.")
			if stock_row.t_warehouse != warehouse:
				raise WorkflowError("WAREHOUSE_PERMISSION_DENIED", f"Source row warehouse is {stock_row.t_warehouse}, not {warehouse}.")
			for suggested in _putaway_allocations(stock_entry, stock_row):
				allocation.append("locations", {
					"allocation_id": str(uuid.uuid4()), "source_doctype": "Stock Entry",
					"source_document": stock_entry.name, "source_row": stock_row.name,
					"item_code": stock_row.item_code, "stock_uom": stock_row.stock_uom,
					"original_qty": suggested["stock_quantity"],
					"suggested_location": suggested["inventory_location_id"],
					"suggested_qty": suggested["stock_quantity"], "actual_qty": suggested["stock_quantity"],
					"priority": suggested.get("priority") or 0, "putaway_rule": suggested.get("putaway_rule") or "",
					"status": "PENDING_VERIFICATION",
				})
		if not allocation.locations:
			raise WorkflowError("INSUFFICIENT_PUTAWAY_CAPACITY", "No Putaway allocation could be created.")
		allocation.locations.sort(key=lambda row: (row.priority, _natural_key(row.suggested_location)))
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
		doc = _load_allocation(warehouse_allocation, user)
		if doc.picker != picker.name and user != "Administrator":
			raise WorkflowError("PICKER_NOT_AUTHORIZED", "This allocation belongs to another Picker.", status=403)
		row = _row(doc, allocation_id)
		if row.item_code != item_code:
			raise WorkflowError("LOCATION_ITEM_MISMATCH", "The scanned item does not match this allocation.")
		quantity = _decimal(actual_quantity, positive=True)
		if quantity != Decimal(str(row.actual_qty or row.suggested_qty or 0)):
			raise WorkflowError("INVALID_QUANTITY", "Use Adjust Quantity with a reason before verifying a different quantity.")
		location = _validate_location(doc, row, scanned_location_id, quantity)
		row.actual_location = location.name
		row.actual_qty = quantity
		row.status = "VERIFIED"
		row.scanner_id = device_id
		row.user = user
		row.scan_time = now_datetime()
		doc.status = "In Progress"
		doc.save(ignore_permissions=True)
		_audit("LOCATION_VERIFIED", doc, row, request.name, device_id=device_id)
		return finish_request(request, _response(doc))
	except WorkflowError as exc:
		return error_response(exc)
	except Exception as exc:
		return error_response(WorkflowError("ERP_VALIDATION_FAILED", str(exc)))


@frappe.whitelist(allow_guest=True)
def change_location(warehouse_allocation, allocation_id, new_location_id, actual_quantity,
	reason, transaction_id, device_id=None, mobile_token=None):
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
		doc = _load_allocation(warehouse_allocation, user)
		if doc.picker != picker.name and user != "Administrator":
			raise WorkflowError("PICKER_NOT_AUTHORIZED", "This allocation belongs to another Picker.", status=403)
		row = _row(doc, allocation_id)
		quantity = _decimal(actual_quantity, positive=True)
		previous = row.actual_location or ""
		location = _validate_location(doc, row, new_location_id, quantity)
		row.actual_location, row.actual_qty, row.status = location.name, quantity, "VERIFIED"
		row.scanner_id, row.user, row.scan_time = device_id, user, now_datetime()
		doc.save(ignore_permissions=True)
		_audit("LOCATION_CHANGED", doc, row, request.name, reason, device_id,
			details_json=json.dumps({"previous_actual_location": previous}))
		return finish_request(request, _response(doc))
	except WorkflowError as exc:
		return error_response(exc)
	except Exception as exc:
		return error_response(WorkflowError("ERP_VALIDATION_FAILED", str(exc)))


@frappe.whitelist(allow_guest=True)
def adjust_quantity(warehouse_allocation, allocation_id, actual_quantity, reason,
	transaction_id, device_id=None, mobile_token=None):
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
		doc = _load_allocation(warehouse_allocation, user)
		if doc.picker != picker.name and user != "Administrator":
			raise WorkflowError("PICKER_NOT_AUTHORIZED", "This allocation belongs to another Picker.", status=403)
		row = _row(doc, allocation_id)
		quantity = _decimal(actual_quantity)
		previous = Decimal(str(row.actual_qty or row.suggested_qty or 0))
		if quantity != previous and not str(reason or "").strip():
			raise WorkflowError("ERP_VALIDATION_FAILED", "A reason is required when quantity changes.")
		row.actual_qty = quantity
		row.status = "PENDING_VERIFICATION" if not row.actual_location else "CONFLICTED"
		doc.save(ignore_permissions=True)
		_audit("QUANTITY_ADJUSTED", doc, row, request.name, reason, device_id,
			details_json=json.dumps({"previous_actual_quantity": str(previous)}))
		return finish_request(request, _response(doc))
	except WorkflowError as exc:
		return error_response(exc)
	except Exception as exc:
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
		by_source = {}
		for row in doc.locations:
			by_source.setdefault(row.source_document, []).append(row)
		for stock_entry_name, rows in by_source.items():
			stock_entry = _draft_stock_entry(stock_entry_name, user, mutate=True)
			batch = frappe.get_doc("Scanner Warehouse Handover", doc.handover)
			versions = {row.stock_entry_row: str(row.source_modified) for row in batch.source_stock_entries if row.stock_entry == stock_entry_name}
			if any(str(stock_entry.modified) != version for version in versions.values()):
				raise WorkflowError("SOURCE_DOCUMENT_CHANGED", f"Stock Entry '{stock_entry.name}' changed after Checker verification.")
			finished = [item for item in stock_entry.items if item.is_finished_item and item.t_warehouse]
			entries = []
			for source in finished:
				source_allocations = [row for row in rows if row.source_row == source.name]
				if not source_allocations:
					continue
				suggestions = list(_putaway_allocations(stock_entry, source))
				unused = list(suggestions)
				for allocated in source_allocations:
					suggested = next((item for item in unused if item["inventory_location_id"] == allocated.suggested_location), None)
					if not suggested and unused:
						suggested = unused[0]
					if not suggested:
						raise WorkflowError("SOURCE_DOCUMENT_CHANGED", "Putaway Rules changed after allocation creation.")
					unused.remove(suggested)
					factor = Decimal(str(source.conversion_factor or 1))
					entries.append({
						"allocation_id": suggested["allocation_id"], "stock_entry_row": source.name,
						"item_code": source.item_code, "uom": source.uom,
						"quantity": Decimal(str(allocated.actual_qty)) / factor,
						"inventory_location_id": allocated.actual_location, "device_id": device_id,
					})
			if not entries:
				raise WorkflowError("ALLOCATION_INCOMPLETE", "No verified source rows are available for completion.")
			try:
				_split_finished_rows(stock_entry, finished, entries)
			except ScannerAPIError as exc:
				raise WorkflowError(exc.code, str(exc), exc.details)
			stock_entry.save(ignore_permissions=True)
		doc.status = "Completed"
		doc.completed_at = now_datetime()
		doc.save(ignore_permissions=True)
		batch = frappe.get_doc("Scanner Warehouse Handover", doc.handover)
		batch.status, batch.completed_at, batch.picker = "COMPLETED", now_datetime(), picker.name
		batch.save(ignore_permissions=True)
		_audit("ALLOCATION_COMPLETED", doc, request_id=request.name, device_id=device_id)
		response = _response(doc)
		response["source_documents"] = [{"stock_entry_id": name, "docstatus": 0, "status": "Draft"} for name in by_source]
		return finish_request(request, response)
	except WorkflowError as exc:
		return error_response(exc)
	except Exception as exc:
		frappe.log_error(frappe.get_traceback(), "warehouse_allocation.complete")
		return error_response(WorkflowError("ERP_VALIDATION_FAILED", str(exc)))
