import hashlib
import copy
import json
import math
import re
import uuid

import frappe
from frappe.utils import flt, get_datetime, now_datetime

from qcmc_logic.api.stock_reconciliation import _authenticate_request_user
from qcmc_logic.api.stock_entry import (
	_pending_qty,
	make_manufacture_stock_entry_from_job_card,
)
from qcmc_logic.overrides.putaway_rule_dimension import (
	get_dimension_stock_balance,
	get_ordered_dimension_putaway_rules,
)
from qcmc_logic.utils import ensure_scanner_warehouse_access


class ScannerAPIError(frappe.ValidationError):
	def __init__(self, code, message, details=None):
		self.code, self.details = code, details or {}
		super().__init__(message)


def _error(code, message, details=None, status=400):
	frappe.local.response["http_status_code"] = status
	return {"success": False, "error_code": code, "message": message, "details": details or {}}


def _stock_entry_id(value):
	value = str(value or "").strip()
	if value.startswith("{"):
		try:
			payload = json.loads(value)
			value = str(payload.get("stock_entry_id") or payload.get("document_id") or "").strip()
		except (TypeError, ValueError):
			pass
	match = re.search(r"(?:/stock-entry/)?([A-Za-z0-9_-]+)$", value.rstrip("/"))
	return match.group(1) if match else value


def _purpose(doc):
	return frappe.db.get_value("Stock Entry Type", doc.stock_entry_type, "purpose") or doc.purpose


def _stock_entry_warehouses(doc, fallback_rows=None):
	rows = doc.get("items") if hasattr(doc, "get") else getattr(doc, "items", None)
	rows = rows or fallback_rows or []
	return [row.get("s_warehouse") for row in rows] + [row.get("t_warehouse") for row in rows]


def _validate_document(stock_entry_id, permission="read"):
	stock_entry_id = _stock_entry_id(stock_entry_id)
	if not frappe.db.exists("Stock Entry", stock_entry_id):
		raise ScannerAPIError("STOCK_ENTRY_NOT_FOUND", f"Stock Entry '{stock_entry_id}' was not found.")
	doc = frappe.get_doc("Stock Entry", stock_entry_id)
	doc.check_permission(permission)
	if doc.docstatus != 0:
		raise ScannerAPIError("STOCK_ENTRY_NOT_DRAFT", f"Stock Entry '{doc.name}' is not Draft.")
	if _purpose(doc) != "Manufacture":
		raise ScannerAPIError("INVALID_OPERATION", "Stock Entry purpose must be Manufacture.")
	finished = [row for row in doc.items if row.is_finished_item and row.t_warehouse]
	if not finished:
		raise ScannerAPIError("FINISHED_ITEM_NOT_FOUND", "No receivable finished-item row exists.")
	return doc, finished


def _item_result(row):
	item = frappe.db.get_value("Item", row.item_code, ["item_name", "has_batch_no", "has_serial_no"], as_dict=True) or {}
	return {
		"stock_entry_row": row.name, "row_name": row.name, "item_code": row.item_code,
		"item_name": item.get("item_name") or row.item_name or row.item_code,
		"expected_quantity": flt(row.qty), "already_confirmed_quantity": 0,
		"remaining_quantity": flt(row.qty), "uom": row.uom, "stock_uom": row.stock_uom,
		"conversion_factor": flt(row.conversion_factor), "target_warehouse": row.t_warehouse,
		"inventory_location": row.get("to_location") or "",
		"requires_batch": bool(item.get("has_batch_no")),
		"requires_serial_number": bool(item.get("has_serial_no")),
	}


def _resolve_storage_location(identity, require_leaf=False, allow_legacy_code=False):
	"""Load a Storage Location and expose its document name as canonical ID.

	Legacy location-code lookup is intentionally limited to old Putaway Rule
	data. Scanner submissions must provide the exact linked document name.
	"""
	identity = str(identity or "").strip()
	if not identity:
		code = "PUTAWAY_LOCATION_NOT_FOUND" if allow_legacy_code else "LOCATION_NOT_FOUND"
		raise ScannerAPIError(code, "Storage Location is required.")
	fields = ["name", "location_code", "location_name", "location_type", "parent_storage_location", "is_group", "disabled", "custom_warehouse"]
	location = frappe.db.get_value("Storage Location", identity, fields, as_dict=True)
	if not location and allow_legacy_code:
		matches = frappe.get_all(
			"Storage Location", filters={"location_code": identity}, fields=fields, limit=2
		)
		if len(matches) > 1:
			raise ScannerAPIError(
				"PUTAWAY_LOCATION_AMBIGUOUS",
				"Storage Location code is ambiguous.",
				{"location_code": identity},
			)
		location = matches[0] if matches else None
	if not location:
		if allow_legacy_code:
			raise ScannerAPIError(
				"PUTAWAY_LOCATION_NOT_FOUND",
				"Storage Location could not be resolved from Putaway Rule.",
				{"location": identity},
			)
		raise ScannerAPIError("LOCATION_NOT_FOUND", f"Storage Location '{identity}' does not exist.")
	if location.disabled:
		raise ScannerAPIError("LOCATION_DISABLED", f"Storage Location '{location.name}' is disabled.")
	if require_leaf and (location.is_group or location.location_type == "Building"):
		raise ScannerAPIError("LOCATION_IS_GROUP", f"Storage Location '{location.name}' is not an enabled posting leaf.")
	location.inventory_location_id = location.name
	location.inventory_location_code = str(location.location_code or "").strip()
	location.inventory_location_name = str(location.location_name or location.name).strip()
	return location


def _parent_distribution(finished, allocations):
	"""Return the one safe backend-controlled parent, otherwise exact mode."""
	if not allocations or not finished:
		return "exact_location", None
	row = finished[0]
	if any(r.item_code != row.item_code or r.t_warehouse != row.t_warehouse or r.uom != row.uom for r in finished):
		return "exact_location", None
	if any(
		a["item_code"] != row.item_code
		or a["target_warehouse"] != row.t_warehouse
		or a["uom"] != row.uom
		or not a.get("putaway_rule")
		for a in allocations
	):
		return "exact_location", None
	parent_names = {a.get("parent_location_name") for a in allocations}
	if len(parent_names) != 1 or not next(iter(parent_names)):
		return "exact_location", None
	parent = _resolve_storage_location(next(iter(parent_names)))
	if not parent.is_group or parent.location_type != "Aisle":
		return "exact_location", None
	expected = sum(flt(r.qty) for r in finished)
	if not math.isclose(sum(flt(a["quantity"]) for a in allocations), expected, rel_tol=0, abs_tol=1e-9):
		return "exact_location", None
	return "parent_location", {
		"location_id": parent.inventory_location_id,
		"location_name": parent.inventory_location_name,
		"warehouse": row.t_warehouse,
	}


def _validate_distribution_parent(distribution_mode, distribution_parent, entries, distribution_parent_id=None):
	if distribution_mode != "parent_location":
		return
	entry_parents = {
		str(e.get("distribution_parent_id") or e.get("parent_location_id") or "").strip()
		for e in entries
	}
	entry_parents.discard("")
	if len(entry_parents) > 1:
		raise ScannerAPIError("INVALID_INVENTORY_LOCATION", "Submitted allocations contain different distribution parents.")
	submitted_parent = str(distribution_parent_id or "").strip() or (next(iter(entry_parents)) if entry_parents else "")
	if not submitted_parent:
		return  # Backward compatibility for exact-allocation scanner releases.
	parent = _resolve_storage_location(submitted_parent)
	if parent.inventory_location_id != distribution_parent["location_id"]:
		raise ScannerAPIError("INVALID_INVENTORY_LOCATION", "The scanned distribution parent does not match the ERPNext allocation parent.")


def _putaway_allocations(doc, row):
	"""Return authoritative priority/capacity allocations for one finished row."""
	# Once a scanner submission has split a row, retain its authoritative
	# allocation identity and recommendation. Do not recalculate or reorder it.
	if row.get("custom_putaway_allocation_id") and row.get("custom_recommended_storage_location"):
		recommended = _resolve_storage_location(row.custom_recommended_storage_location, require_leaf=True)
		actual = _resolve_storage_location(row.get("custom_actual_storage_location") or recommended.name, require_leaf=True)
		for location in (recommended, actual):
			if _normalize_warehouse(row.t_warehouse) != _normalize_warehouse(location.custom_warehouse):
				raise ScannerAPIError(
					"PUTAWAY_LOCATION_WAREHOUSE_MISMATCH",
					f"Stock Entry target warehouse '{row.t_warehouse}' does not match Storage Location warehouse '{location.custom_warehouse or ''}'.",
				)
		return [{
			"allocation_id": row.custom_putaway_allocation_id,
			"stock_entry_row": row.name,
			"item_code": row.item_code,
			"item_name": row.item_name or row.item_code,
			"quantity": flt(row.qty),
			"stock_quantity": flt(row.transfer_qty) or flt(row.qty) * (flt(row.conversion_factor) or 1),
			"uom": row.uom,
			"stock_uom": row.stock_uom,
			"conversion_factor": flt(row.conversion_factor) or 1,
			"target_warehouse": row.t_warehouse,
			"inventory_location": actual.inventory_location_id,
			"inventory_location_id": actual.inventory_location_id,
			"inventory_location_code": actual.inventory_location_code,
			"inventory_location_name": actual.inventory_location_name,
			"recommended_inventory_location": recommended.inventory_location_id,
			"location_overridden": bool(row.get("custom_location_overridden")),
			"parent_location_id": "",
			"parent_location_name": "",
			"putaway_rule": row.putaway_rule,
			"priority": 0,
			"allocation_source": "putaway_rule" if row.putaway_rule else "general_purpose_location",
			"unlimited_capacity": not bool(row.putaway_rule),
			"requires_batch": bool(frappe.db.get_value("Item", row.item_code, "has_batch_no")),
			"requires_serial_number": bool(frappe.db.get_value("Item", row.item_code, "has_serial_no")),
		}]
	at_capacity, rules = get_ordered_dimension_putaway_rules(
		row.item_code, doc.company, source_warehouse=row.s_warehouse
	)
	rules = [rule for rule in (rules or []) if rule.warehouse == row.t_warehouse]
	pending_stock_qty = flt(row.transfer_qty) or flt(row.qty) * (flt(row.conversion_factor) or 1)
	conversion_factor = flt(row.conversion_factor) or 1
	item = frappe.db.get_value("Item", row.item_code, ["has_batch_no", "has_serial_no"], as_dict=True) or {}
	allocations = []
	for rule in rules:
		location_identity = str(rule.get("location") or "").strip()
		if not location_identity or pending_stock_qty <= 0:
			continue
		location = _resolve_storage_location(
			location_identity, require_leaf=True, allow_legacy_code=True
		)
		if _normalize_warehouse(rule.warehouse) != _normalize_warehouse(location.custom_warehouse):
			raise ScannerAPIError(
				"PUTAWAY_LOCATION_WAREHOUSE_MISMATCH",
				f"Putaway Rule warehouse '{rule.warehouse}' does not match Storage Location warehouse '{location.custom_warehouse or ''}'.",
				{"putaway_rule": rule.name, "putaway_rule_warehouse": rule.warehouse, "storage_location": location.name, "storage_location_warehouse": location.custom_warehouse or ""},
			)
		if _normalize_warehouse(row.t_warehouse) != _normalize_warehouse(rule.warehouse):
			raise ScannerAPIError(
				"PUTAWAY_LOCATION_WAREHOUSE_MISMATCH",
				f"Stock Entry target warehouse '{row.t_warehouse}' does not match Putaway Rule warehouse '{rule.warehouse}'.",
			)
		parent = _resolve_storage_location(location.parent_storage_location) if location.parent_storage_location else None
		stock_qty = min(pending_stock_qty, flt(rule.free_space))
		if stock_qty <= 0:
			continue
		qty = stock_qty / conversion_factor
		allocations.append({
			"allocation_id": f"{row.name}:{rule.name}:{location.inventory_location_id}",
			"stock_entry_row": row.name,
			"item_code": row.item_code,
			"item_name": row.item_name or row.item_code,
			"quantity": qty,
			"stock_quantity": stock_qty,
			"uom": row.uom,
			"stock_uom": row.stock_uom,
			"conversion_factor": conversion_factor,
			"target_warehouse": rule.warehouse,
			"inventory_location": location.inventory_location_id,
			"inventory_location_id": location.inventory_location_id,
			"inventory_location_code": location.inventory_location_code,
			"inventory_location_name": location.inventory_location_name,
			"recommended_inventory_location": location.inventory_location_id,
			"location_overridden": False,
			"parent_location_id": parent.inventory_location_id if parent else "",
			"parent_location_name": parent.name if parent else "",
			"parent_location_display_name": parent.inventory_location_name if parent else "",
			"putaway_rule": rule.name,
			"priority": rule.priority,
			"allocation_source": "putaway_rule",
			"unlimited_capacity": False,
			"requires_batch": bool(item.get("has_batch_no")),
			"requires_serial_number": bool(item.get("has_serial_no")),
		})
		pending_stock_qty -= stock_qty
	if pending_stock_qty > 1e-9:
		fallback = _general_purpose_location(row.t_warehouse, allocations)
		if fallback:
			qty = pending_stock_qty / conversion_factor
			allocations.append({
				"allocation_id": f"{row.name}:general:{fallback.name}",
				"stock_entry_row": row.name,
				"item_code": row.item_code,
				"item_name": row.item_name or row.item_code,
				"quantity": qty,
				"stock_quantity": pending_stock_qty,
				"uom": row.uom,
				"stock_uom": row.stock_uom,
				"conversion_factor": conversion_factor,
				"target_warehouse": fallback.custom_warehouse,
				"inventory_location": fallback.inventory_location_id,
				"inventory_location_id": fallback.inventory_location_id,
				"inventory_location_code": fallback.inventory_location_code,
				"inventory_location_name": fallback.inventory_location_name,
				"recommended_inventory_location": fallback.inventory_location_id,
				"location_overridden": False,
				"parent_location_id": "",
				"parent_location_name": "",
				"putaway_rule": "",
				"priority": fallback.putaway_priority,
				"requires_batch": bool(item.get("has_batch_no")),
				"requires_serial_number": bool(item.get("has_serial_no")),
				"allocation_source": "general_purpose_location",
				"unlimited_capacity": True,
			})
			pending_stock_qty = 0
	if pending_stock_qty > 1e-9:
		message = f"Putaway Rule capacity is short by {pending_stock_qty:g} {row.stock_uom or row.uom} for {row.item_code}."
		if not rules and not at_capacity:
			message = f"No available Putaway Rule exists for {row.item_code} in {row.t_warehouse}."
		raise ScannerAPIError("INSUFFICIENT_PUTAWAY_CAPACITY", message)
	return allocations


def _general_purpose_location(target_warehouse, explicit_allocations=None):
	"""Discover one unrestricted, unlimited posting leaf directly from ERP."""
	priority_field = "custom_putaway_priority"
	has_priority = frappe.get_meta("Storage Location").has_field(priority_field)
	fields = [
		"name", "location_code", "location_name", "location_type",
		"parent_storage_location", "is_group", "disabled", "custom_warehouse",
		"custom_restricted_item", "custom_storage_capacity",
	]
	if has_priority:
		fields.append(priority_field)
	excluded = set()
	for allocation in explicit_allocations or []:
		excluded.add(str(allocation.get("inventory_location_id") or allocation.get("inventory_location") or "").strip())
		excluded.add(str(allocation.get("inventory_location_name") or "").strip())
	candidates = []
	for location in frappe.get_all(
		"Storage Location", filters={"disabled": 0, "is_group": 0}, fields=fields
	):
		warehouse = str(location.get("custom_warehouse") or "").strip()
		if not warehouse or _normalize_warehouse(warehouse) != _normalize_warehouse(target_warehouse):
			continue
		if str(location.get("custom_restricted_item") or "").strip():
			continue
		if flt(location.get("custom_storage_capacity")) > 0:
			continue
		location_id = location.name
		if location_id in excluded or location.name in excluded:
			continue
		location.inventory_location_id = location_id
		location.inventory_location_code = str(location.get("location_code") or "").strip()
		location.inventory_location_name = str(location.get("location_name") or location.name).strip()
		location.putaway_priority = flt(location.get(priority_field)) if has_priority and location.get(priority_field) not in (None, "") else 1000
		candidates.append(location)
	candidates.sort(key=lambda location: (location.putaway_priority, _natural_location_key(location.inventory_location_id)))
	return candidates[0] if candidates else None


def _natural_location_key(value):
	return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", str(value or ""))]


def _auth(mobile_token):
	user = _authenticate_request_user(mobile_token)
	if not user or user == "Guest":
		raise ScannerAPIError("PERMISSION_DENIED", "Session expired. Please log in again.")
	return user


@frappe.whitelist(allow_guest=True)
def get_storage_location_details(inventory_location_id=None, location_id=None, mobile_token=None):
	"""Resolve a compact Storage Location QR to authoritative ERP details."""
	try:
		user = _auth(mobile_token)
		identity = str(inventory_location_id or location_id or "").strip()
		location = _resolve_storage_location(identity)
		if not frappe.has_permission("Storage Location", "read", doc=location.name):
			raise ScannerAPIError(
				"PERMISSION_DENIED", "You do not have permission to read this Storage Location."
			)
		details = frappe.db.get_value(
			"Storage Location",
			location.name,
			[
				"name", "location_code", "location_name", "location_type", "full_path",
				"custom_warehouse", "is_group", "disabled", "custom_restricted_item",
				"custom_storage_capacity",
			],
			as_dict=True,
		)
		ensure_scanner_warehouse_access(user, [details.custom_warehouse])
		return {
			"success": True,
			"inventory_location_id": details.name,
			"location_id": details.name,
			"location_code": details.location_code,
			"location_name": details.location_name,
			"location_type": details.location_type,
			"location_path": details.full_path or "",
			"warehouse": details.custom_warehouse or "",
			"is_group": bool(details.is_group),
			"disabled": bool(details.disabled),
			"item_code": details.custom_restricted_item or "",
			"storage_capacity": flt(details.custom_storage_capacity),
		}
	except ScannerAPIError as exc:
		return _error(exc.code, str(exc), exc.details, 403 if exc.code == "PERMISSION_DENIED" else 400)
	except frappe.PermissionError:
		return _error(
			"PERMISSION_DENIED", "You do not have permission to read this Storage Location.", status=403
		)
	except Exception as exc:
		return _error("ERP_VALIDATION_FAILED", str(exc))


def _manufacture_receive_context(doc, finished):
	allocations = [allocation for row in finished for allocation in _putaway_allocations(doc, row)]
	distribution_mode, distribution_parent = _parent_distribution(finished, allocations)
	return {
		"success": True,
		"stock_entry_id": doc.name,
		"stock_entry_type": doc.stock_entry_type,
		"purpose": _purpose(doc),
		"work_order_id": doc.work_order,
		"work_order": doc.work_order,
		"job_card_id": doc.get("custom_final_job_card") or doc.job_card or "",
		"job_card": doc.get("custom_final_job_card") or doc.job_card or "",
		"custom_reference_document": doc.get("custom_reference_document") or "",
		"company": doc.company,
		"docstatus": doc.docstatus,
		"status": "Draft",
		"finished_items": [_item_result(row) for row in finished],
		"putaway_allocations": allocations,
		"allocation_count": len(allocations),
		"distribution_mode": distribution_mode,
		"distribution_parent": distribution_parent,
	}


def _job_card_id(value):
	"""Accept a Job Card name or the five-part QCMC packing-label QR value."""
	value = str(value or "").strip()
	if value.startswith("{"):
		try:
			payload = json.loads(value)
			value = str(payload.get("job_card_id") or payload.get("job_card") or "").strip()
		except (TypeError, ValueError):
			pass
	if ";" in value:
		parts = [part.strip() for part in value.split(";")]
		value = parts[4] if len(parts) >= 5 else ""
	match = re.search(r"(?:/job-card/)?([A-Za-z0-9_-]+)$", value.rstrip("/"))
	return match.group(1) if match else value


@frappe.whitelist(allow_guest=True)
def create_manufacture_receive_draft(
	job_card_id,
	custom_reference_document,
	quantity=None,
	mobile_token=None,
):
	"""Create the scanner's Manufacture Stock Entry as Draft; never submit it."""
	savepoint_started = False
	try:
		user = _auth(mobile_token)
		job_card_id = _job_card_id(job_card_id)
		reference = str(custom_reference_document or "").strip()
		if not job_card_id or not frappe.db.exists("Job Card", job_card_id):
			raise ScannerAPIError("JOB_CARD_NOT_FOUND", f"Job Card '{job_card_id}' was not found.")
		if not reference:
			raise ScannerAPIError("PULL_OUT_SLIP_REQUIRED", "Pull Out Slip is required.")
		if not frappe.get_meta("Stock Entry").has_field("custom_reference_document"):
			raise ScannerAPIError("ERP_CONFIGURATION_ERROR", "Stock Entry is missing custom_reference_document.")

		frappe.db.savepoint("create_manufacture_receive_draft")
		savepoint_started = True
		frappe.db.sql("select name from `tabJob Card` where name=%s for update", job_card_id)

		# A retry of the Create action reuses the same Draft. A different Pull Out
		# Slip must not silently take over an already-open manufacturing document.
		existing = frappe.db.get_value(
			"Stock Entry",
			{
				"docstatus": 0,
				"purpose": "Manufacture",
				"custom_final_job_card": job_card_id,
				"custom_reference_document": reference,
			},
			"name",
		)
		if existing:
			doc, finished = _validate_document(existing, "read")
			ensure_scanner_warehouse_access(
				user,
				_stock_entry_warehouses(doc, finished),
				require_transact=True,
			)
			result = _manufacture_receive_context(doc, finished)
			result["existing_draft"] = True
			return result

		job_card = frappe.get_doc("Job Card", job_card_id)
		requested_qty = flt(quantity) if quantity not in (None, "") else _pending_qty(job_card, "Manufacture")
		created = make_manufacture_stock_entry_from_job_card(job_card_id, requested_qty)
		doc = frappe.get_doc("Stock Entry", created["name"])
		ensure_scanner_warehouse_access(
			user,
			_stock_entry_warehouses(doc),
			require_transact=True,
		)
		doc.custom_reference_document = reference
		doc.save()
		if doc.docstatus != 0:
			raise ScannerAPIError("STOCK_ENTRY_NOT_DRAFT", "Scanner-created Stock Entry must remain Draft.")
		finished = [row for row in doc.items if row.is_finished_item and row.t_warehouse]
		result = _manufacture_receive_context(doc, finished)
		result["existing_draft"] = False
		return result
	except ScannerAPIError as exc:
		if savepoint_started:
			frappe.db.rollback(save_point="create_manufacture_receive_draft")
		return _error(exc.code, str(exc), exc.details, 403 if exc.code == "PERMISSION_DENIED" else 400)
	except frappe.PermissionError:
		if savepoint_started:
			frappe.db.rollback(save_point="create_manufacture_receive_draft")
		return _error("PERMISSION_DENIED", "You do not have permission to create this Draft Stock Entry.", status=403)
	except Exception as exc:
		if savepoint_started:
			frappe.db.rollback(save_point="create_manufacture_receive_draft")
		return _error("ERP_VALIDATION_FAILED", str(exc))


@frappe.whitelist(allow_guest=True)
def get_manufacture_receive_context(stock_entry_id, mobile_token=None):
	try:
		user = _auth(mobile_token)
		doc, finished = _validate_document(stock_entry_id, "read")
		ensure_scanner_warehouse_access(
			user,
			_stock_entry_warehouses(doc, finished),
		)
		return _manufacture_receive_context(doc, finished)
	except ScannerAPIError as exc:
		return _error(exc.code, str(exc), exc.details, 403 if exc.code == "PERMISSION_DENIED" else 400)
	except frappe.PermissionError:
		return _error("PERMISSION_DENIED", "You do not have permission to read this Stock Entry.", status=403)


def _canonical(stock_entry_id, submission_id, entries, distribution_parent_id=None):
	payload = {"stock_entry_id": stock_entry_id, "operation": "receive_manufacture", "submission_id": submission_id, "entries": entries}
	if distribution_parent_id:
		payload["distribution_parent_id"] = str(distribution_parent_id).strip()
	text = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
	return text, hashlib.sha256(text.encode()).hexdigest()


def _get_idempotent_replay(submission_id, request_hash):
	replay = frappe.db.get_value(
		"Manufacture Receive Submission",
		submission_id,
		["request_hash", "result_json"],
		as_dict=True,
	)
	if not replay:
		return None
	if replay.request_hash != request_hash:
		raise ScannerAPIError(
			"SUBMISSION_ID_CONFLICT",
			"submission_id was reused with different content.",
		)
	result = json.loads(replay.result_json)
	result["duplicate_submission"] = True
	return result


def _uuid(value):
	if not str(value or "").strip():
		raise ScannerAPIError("SUBMISSION_ID_REQUIRED", "submission_id is required.")
	try: return str(uuid.UUID(str(value or "").strip()))
	except Exception: raise ScannerAPIError("ERP_VALIDATION_FAILED", "submission_id must be a valid UUID.")


def _transaction_time(value):
	try: return get_datetime(value) if value else now_datetime()
	except Exception: return now_datetime()


def _resolve_finished_item_putaway(doc, row, scanned_location):
	"""Resolve the next ERPNext Putaway Rule without affecting Physical Count."""
	at_capacity, rules = get_ordered_dimension_putaway_rules(
		row.item_code, doc.company, source_warehouse=row.s_warehouse
	)
	rules = [rule for rule in (rules or []) if rule.warehouse == row.t_warehouse]
	if not rules:
		message = f"No available Putaway Rule exists for {row.item_code} in {row.t_warehouse}."
		if at_capacity:
			message = f"Putaway Rule capacity is exhausted for {row.item_code} in {row.t_warehouse}."
		raise ScannerAPIError("INVALID_INVENTORY_LOCATION", message)
	rule = rules[0]
	rule_location = str(rule.get("location") or "").strip()
	if not rule_location:
		raise ScannerAPIError("INVALID_INVENTORY_LOCATION", f"Putaway Rule '{rule.name}' has no target Inventory Location.")
	if scanned_location != rule_location:
		raise ScannerAPIError(
			"INVALID_INVENTORY_LOCATION",
			f"Next Putaway Rule location for {row.item_code} is {rule_location}, not {scanned_location}.",
			{"putaway_rule": rule.name, "expected_location": rule_location, "scanned_location": scanned_location},
		)
	stock_qty = flt(row.transfer_qty) or flt(row.qty) * (flt(row.conversion_factor) or 1)
	if flt(rule.free_space) + 1e-9 < stock_qty:
		raise ScannerAPIError(
			"INVALID_INVENTORY_LOCATION",
			f"Putaway Rule '{rule.name}' has capacity {flt(rule.free_space):g}, but {stock_qty:g} is required.",
		)
	return rule


def _validate_override_location(allocation, location, reserved_stock_qty=0):
	"""Validate an operator override from Storage Location data, never Putaway Rules."""
	location_data = frappe.db.get_value(
		"Storage Location",
		location.name,
		["custom_warehouse", "custom_restricted_item", "custom_storage_capacity"],
		as_dict=True,
	) or {}
	location_warehouse = str(location_data.get("custom_warehouse") or "").strip()
	if not location_warehouse:
		raise ScannerAPIError(
			"STORAGE_LOCATION_WAREHOUSE_REQUIRED",
			f"Location '{location.inventory_location_id}' has no Warehouse configured.",
		)
	if _normalize_warehouse(location_warehouse) != _normalize_warehouse(allocation["target_warehouse"]):
		raise ScannerAPIError(
			"LOCATION_WAREHOUSE_MISMATCH",
			f"Location '{location.inventory_location_id}' does not belong to {allocation['target_warehouse']}.",
		)
	restricted_item = str(location_data.get("custom_restricted_item") or "").strip()
	if restricted_item and restricted_item != allocation["item_code"]:
		raise ScannerAPIError(
			"LOCATION_ITEM_MISMATCH",
			f"Location '{location.inventory_location_id}' is restricted to Item {restricted_item}.",
		)
	balance = get_dimension_stock_balance(
		allocation["item_code"], allocation["target_warehouse"], {"location": location.name}
	)
	capacity = flt(location_data.get("custom_storage_capacity"))
	# A blank/zero capacity is intentionally unlimited. Only a positive
	# configured capacity constrains an operator-selected override location.
	available = capacity - flt(balance) - flt(reserved_stock_qty) if capacity > 0 else None
	if capacity > 0 and available + 1e-9 < flt(allocation["stock_quantity"]):
		raise ScannerAPIError(
			"INSUFFICIENT_PUTAWAY_CAPACITY",
			f"Location '{location.inventory_location_id}' has {max(available, 0):g} {allocation['stock_uom']} available; {flt(allocation['stock_quantity']):g} is required.",
			{"capacity": capacity, "balance": flt(balance), "reserved": flt(reserved_stock_qty), "available_capacity": max(available, 0)},
		)


def _draft_override_reservation(stock_entry, item_code, warehouse, location_name):
	"""Count other scanner-saved Draft rows as reserved capacity."""
	return flt(frappe.db.sql(
		"""
		select coalesce(sum(sed.transfer_qty), 0)
		from `tabStock Entry Detail` sed
		inner join `tabStock Entry` se on se.name = sed.parent
		where se.docstatus = 0 and se.name != %s
		  and sed.item_code = %s and sed.t_warehouse = %s
		  and sed.custom_actual_storage_location = %s
		""",
		(stock_entry, item_code, warehouse, location_name),
	)[0][0])


def _validate_allocation_entry(doc, entry, allocation, index, reserved_stock_qty=0):
	if str(entry.get("allocation_id") or "").strip() != allocation["allocation_id"]:
		raise ScannerAPIError(
			"ALLOCATION_NOT_FOUND",
			f"Entry #{index}: allocation_id does not belong to the ERPNext allocation.",
			{"expected_allocation_id": allocation["allocation_id"]},
		)
	if entry.get("stock_entry_row") and str(entry.get("stock_entry_row")).strip() != allocation["stock_entry_row"]:
		raise ScannerAPIError("STOCK_ENTRY_ROW_MISMATCH", f"Entry #{index}: Stock Entry row does not match the allocation.")
	if entry.get("item_code") and str(entry.get("item_code")).strip() != allocation["item_code"]:
		raise ScannerAPIError("ITEM_MISMATCH", f"Entry #{index}: Item does not match ERPNext allocation.")
	if entry.get("uom") and str(entry.get("uom")).strip() != allocation["uom"]:
		raise ScannerAPIError("UOM_MISMATCH", f"Entry #{index}: UOM does not match ERPNext allocation.")
	location_identity = str(entry.get("inventory_location_id") or entry.get("inventory_location") or "").strip()
	try:
		location = _resolve_storage_location(location_identity, require_leaf=True)
	except ScannerAPIError as exc:
		codes = {
			"LOCATION_NOT_FOUND": "STORAGE_LOCATION_NOT_FOUND",
			"LOCATION_DISABLED": "STORAGE_LOCATION_DISABLED",
			"LOCATION_IS_GROUP": "STORAGE_LOCATION_IS_GROUP",
		}
		if exc.code in codes:
			raise ScannerAPIError(codes[exc.code], str(exc), exc.details)
		raise
	expected_location_id = allocation.get("inventory_location_id") or allocation.get("inventory_location")
	qty = flt(entry.get("quantity"))
	if not math.isfinite(qty) or qty <= 0:
		raise ScannerAPIError("INVALID_RECEIVE_QUANTITY", f"Entry #{index}: quantity must be finite and greater than zero.")
	if qty > flt(allocation["quantity"]) + 1e-9:
		raise ScannerAPIError(
			"RECEIVE_QUANTITY_EXCEEDS_REMAINING",
			f"Entry #{index}: quantity cannot exceed the remaining {flt(allocation['quantity']):g} {allocation['uom']}.",
		)
	conversion_factor = flt(allocation.get("conversion_factor")) or 1
	submitted_allocation = dict(allocation)
	submitted_allocation["quantity"] = qty
	submitted_allocation["stock_quantity"] = qty * conversion_factor
	overridden = location.inventory_location_id != expected_location_id
	if overridden or allocation.get("allocation_source") == "general_purpose_location" or not allocation.get("putaway_rule"):
		_validate_override_location(submitted_allocation, location, reserved_stock_qty)
	return location, overridden


def _normalize_warehouse(value):
	"""Compatibility comparison only; ERP writes always use the authoritative value."""
	return re.sub(r"[\s-]+", "", str(value or "").strip().lower())


def _split_finished_rows(doc, finished, entries, distribution_parent_id=None):
	"""Validate every scanned allocation and replace finished rows atomically."""
	entries_by_row = {}
	for entry in entries:
		entries_by_row.setdefault(str(entry.get("stock_entry_row") or "").strip(), []).append(entry)
	updates, audits, overrides = [], [], []
	request_reservations = {}
	finished_names = {row.name for row in finished}
	unknown_rows = set(entries_by_row) - finished_names
	if unknown_rows:
		raise ScannerAPIError(
			"STOCK_ENTRY_ROW_MISMATCH",
			"A submitted Stock Entry row does not belong to this Draft Stock Entry.",
			{"stock_entry_rows": sorted(unknown_rows)},
		)
	new_finished = []
	allocations_by_row = {row.name: _putaway_allocations(doc, row) for row in finished}
	all_allocations = [allocation for allocations in allocations_by_row.values() for allocation in allocations]
	allocation_owners = {
		allocation["allocation_id"]: row_name
		for row_name, allocations in allocations_by_row.items()
		for allocation in allocations
	}
	for row in finished:
		allocations = allocations_by_row[row.name]
		row_entries = entries_by_row.get(row.name, [])
		expected_ids = {allocation["allocation_id"] for allocation in allocations}
		submitted_ids = {str(entry.get("allocation_id") or "").strip() for entry in row_entries}
		unknown_ids = submitted_ids - expected_ids
		if unknown_ids:
			wrong_row_ids = [allocation_id for allocation_id in unknown_ids if allocation_id in allocation_owners]
			if wrong_row_ids:
				raise ScannerAPIError(
					"ALLOCATION_STOCK_ENTRY_MISMATCH",
					"A submitted allocation belongs to a different Stock Entry row.",
					{"allocation_ids": sorted(wrong_row_ids)},
				)
			raise ScannerAPIError(
				"ALLOCATION_NOT_FOUND",
				f"{row.item_code} contains an allocation_id that is not valid for this Stock Entry row.",
				{"invalid_allocation_ids": sorted(unknown_ids)},
			)
		entry_by_allocation = {str(entry.get("allocation_id") or "").strip(): entry for entry in row_entries}
		if len(entry_by_allocation) != len(row_entries):
			raise ScannerAPIError("DUPLICATE_ALLOCATION", f"Duplicate allocation submitted for {row.item_code}.")
		item = frappe.db.get_value("Item", row.item_code, ["item_name", "has_batch_no", "has_serial_no"], as_dict=True)
		remaining_serials = []
		for entry in row_entries:
			remaining_serials.extend(entry.get("serial_numbers") or [])
		for index, allocation in enumerate(allocations, 1):
			entry = entry_by_allocation.get(allocation["allocation_id"])
			if not entry:
				continue
			location_identity = str(entry.get("inventory_location_id") or entry.get("inventory_location") or "").strip()
			location_key = (row.item_code, allocation["target_warehouse"], location_identity)
			reserved = request_reservations.get(location_key, 0)
			if location_identity != (allocation.get("inventory_location_id") or allocation.get("inventory_location")):
				candidate = _resolve_storage_location(location_identity, require_leaf=True)
				reserved += _draft_override_reservation(
					doc.name, row.item_code, allocation["target_warehouse"], candidate.name
				)
			location, overridden = _validate_allocation_entry(doc, entry, allocation, index, reserved)
			submitted_qty = flt(entry.get("quantity"))
			submitted_stock_qty = submitted_qty * (flt(allocation.get("conversion_factor")) or 1)
			request_reservations[location_key] = request_reservations.get(location_key, 0) + submitted_stock_qty
			batch_no = str(entry.get("batch_no") or "").strip()
			if item.has_batch_no and not batch_no:
				raise ScannerAPIError("BATCH_REQUIRED", f"Batch is required for {row.item_code}.")
			if batch_no and not frappe.db.exists("Batch", {"name": batch_no, "item": row.item_code}):
				raise ScannerAPIError("INVALID_BATCH", f"Batch '{batch_no}' is invalid for {row.item_code}.")
			serials = entry.get("serial_numbers") or []
			if item.has_serial_no and len(serials) != int(submitted_stock_qty):
				raise ScannerAPIError("SERIAL_NUMBER_REQUIRED", f"Serial numbers are required for {row.item_code} at {allocation['inventory_location']}.")
			row_dict = copy.deepcopy(row.as_dict())
			for field in ("name", "idx", "parent", "parentfield", "parenttype", "creation", "modified", "owner", "modified_by"):
				row_dict.pop(field, None)
			row_dict.update({
				"qty": submitted_qty, "transfer_qty": submitted_stock_qty,
				"t_warehouse": allocation["target_warehouse"], "to_location": location.name,
				"putaway_rule": allocation["putaway_rule"], "batch_no": batch_no or row.get("batch_no"),
				"serial_no": "\n".join(serials) if serials else "", "serial_and_batch_bundle": "",
				"custom_putaway_allocation_id": allocation["allocation_id"],
				"custom_recommended_storage_location": allocation["inventory_location_id"],
				"custom_actual_storage_location": location.name,
				"custom_location_overridden": int(overridden),
				"custom_location_override_device": str(entry.get("device_id") or "") if overridden else "",
				"custom_location_override_timestamp": now_datetime() if overridden else None,
			})
			new_finished.append(row_dict)
			updates.append({
				"stock_entry_row": row.name, "item_code": row.item_code,
				"item_name": item.item_name or row.item_code, "quantity": submitted_qty,
				"uom": row.uom, "target_warehouse": row.t_warehouse,
				"inventory_location": location.inventory_location_id,
				"inventory_location_name": location.inventory_location_name,
				"recommended_inventory_location": allocation["inventory_location_id"],
				"location_overridden": overridden,
				"putaway_rule": allocation["putaway_rule"],
			})
			if overridden:
					overrides.append({
					"allocation_id": allocation["allocation_id"],
					"recommended_inventory_location": allocation["inventory_location_id"],
					"actual_inventory_location": location.inventory_location_id,
					"quantity": submitted_qty,
					"uom": allocation["uom"],
				})
			for tx in entry.get("transactions") or []:
				audits.append((tx, entry, row, item, {**allocation, "quantity": submitted_qty, "stock_quantity": submitted_stock_qty}))
	distribution_mode, distribution_parent = _parent_distribution(finished, all_allocations)
	_validate_distribution_parent(distribution_mode, distribution_parent, entries, distribution_parent_id)
	# Preserve the original raw-material child objects/names and every existing
	# manufacturing value. Only the finished rows are replaced by allocations.
	raw_rows = [row for row in doc.items if row.name not in finished_names]
	doc.set("items", raw_rows)
	for row_dict in new_finished:
		for field in ("name", "idx", "parent", "parentfield", "parenttype", "creation", "modified", "owner", "modified_by"):
			row_dict.pop(field, None)
		doc.append("items", row_dict)
	return updates, audits, overrides


def _submit(stock_entry_id, submission_id, entries, user, distribution_parent_id=None):
	frappe.db.savepoint("manufacture_receive")
	try:
		stock_entry_id, submission_id = _stock_entry_id(stock_entry_id), _uuid(submission_id)
		request_json, request_hash = _canonical(stock_entry_id, submission_id, entries, distribution_parent_id)
		replay = _get_idempotent_replay(submission_id, request_hash)
		if replay:
			return replay
		frappe.db.sql("select name from `tabStock Entry` where name=%s for update", stock_entry_id)
		# Recheck after waiting for the document lock so concurrent identical
		# retries cannot both update the Draft document.
		replay = _get_idempotent_replay(submission_id, request_hash)
		if replay:
			return replay
		doc, finished = _validate_document(stock_entry_id, "write")
		ensure_scanner_warehouse_access(
			user,
			_stock_entry_warehouses(doc, finished),
			require_transact=True,
		)
		if not isinstance(entries, list) or not entries:
			raise ScannerAPIError("FINISHED_ITEM_NOT_FOUND", "At least one finished-item entry is required.")
		updates, pending_audits, location_overrides = _split_finished_rows(doc, finished, entries, distribution_parent_id)
		doc.save()
		if doc.docstatus != 0:
			raise ScannerAPIError("STOCK_ENTRY_NOT_DRAFT", "Manufacture Stock Entry must remain Draft.")
		result = {"success": True, "stock_entry_id": doc.name, "docstatus": doc.docstatus, "status": "Draft", "submission_id": submission_id, "duplicate_submission": False, "item_count": len(updates), "updated_entries": updates, "location_overrides": location_overrides, "message": "Manufacture Stock Entry saved as Draft."}
		for tx, entry, source_row, item, allocation in pending_audits:
			txid = str(tx.get("id") or "").strip()
			if not txid or frappe.db.exists("Manufacture Receive Scan Transaction", txid):
				continue
			action = str(tx.get("action") or "ADD").upper()
			change = flt(tx.get("quantity_change"))
			frappe.get_doc({"doctype": "Manufacture Receive Scan Transaction", "transaction_id": txid, "submission_id": submission_id, "stock_entry": doc.name, "stock_entry_row": source_row.name, "work_order": doc.work_order, "item_code": source_row.item_code, "item_name": item.item_name, "action": action, "quantity_change": change, "running_quantity": tx.get("running_quantity") or allocation["quantity"], "target_warehouse": allocation["target_warehouse"], "inventory_location": allocation["inventory_location_id"], "employee_id": tx.get("employee_id"), "employee_name": tx.get("employee_name"), "device_id": tx.get("device_id") or entry.get("device_id"), "scanner_timestamp": _transaction_time(tx.get("timestamp")), "server_timestamp": now_datetime()}).insert(ignore_permissions=True)
		frappe.get_doc({"doctype": "Manufacture Receive Submission", "submission_id": submission_id, "stock_entry": doc.name, "processed_by": user, "processed_at": now_datetime(), "device_ids": ", ".join(sorted({str(e.get('device_id') or '') for e in entries})), "request_hash": request_hash, "request_json": request_json, "result_json": json.dumps(result, separators=(",", ":")), "status": "Success"}).insert(ignore_permissions=True)
		frappe.db.commit(); return result
	except Exception:
		frappe.db.rollback(save_point="manufacture_receive"); raise


@frappe.whitelist(allow_guest=True)
def submit_manufacture_receive(stock_entry_id, operation, submission_id, entries, mobile_token=None, distribution_parent_id=None):
	try:
		user = _auth(mobile_token)
		if operation != "receive_manufacture": raise ScannerAPIError("INVALID_OPERATION", "operation must be receive_manufacture.")
		if isinstance(entries, str): entries = json.loads(entries)
		return _submit(stock_entry_id, submission_id, entries, user, distribution_parent_id)
	except ScannerAPIError as exc: return _error(exc.code, str(exc), exc.details, 409 if exc.code == "SUBMISSION_ID_CONFLICT" else 400)
	except frappe.PermissionError: return _error("PERMISSION_DENIED", "You do not have permission to update this Draft Stock Entry.", status=403)
	except Exception as exc: return _error("ERP_VALIDATION_FAILED", str(exc))
