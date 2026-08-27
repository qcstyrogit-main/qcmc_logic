import hashlib
import json
import math
import re
import uuid

import frappe
from frappe.utils import flt, now_datetime

from qcmc_logic.api.stock_entry import (
	_can_use_job_card_for_purpose,
	_get_work_order,
	_job_card_row,
)
from qcmc_logic.api.stock_entry_scanner import ScannerAPIError, _auth, _error
from qcmc_logic.utils import ensure_scanner_warehouse_access


PURPOSE = "Material Transfer for Manufacture"


def _document_id(value):
	value = str(value or "").strip().rstrip("/")
	if value.startswith("{"):
		try:
			payload = json.loads(value)
			value = str(
				payload.get("work_order_id")
				or payload.get("workOrderId")
				or payload.get("job_card_id")
				or payload.get("jobCardId")
				or payload.get("document_id")
				or ""
			).strip()
		except (TypeError, ValueError):
			pass
	match = re.search(r"(?:/work-order/|/job-card/)?([A-Za-z0-9_-]+)$", value)
	return match.group(1) if match else value


def _uuid(value):
	try:
		return str(uuid.UUID(str(value or "").strip()))
	except Exception:
		raise ScannerAPIError("INVALID_SUBMISSION_ID", "submission_id must be a valid UUID.")


def _canonical(job_card, submission_id, entries):
	payload = {
		"operation": "material_transfer_for_manufacture",
		"job_card_id": job_card,
		"submission_id": submission_id,
		"entries": entries,
	}
	request_json = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
	return request_json, hashlib.sha256(request_json.encode()).hexdigest()


def _load_job_card(job_card_id, permission="read"):
	job_card_id = _document_id(job_card_id)
	if not frappe.db.exists("Job Card", job_card_id):
		raise ScannerAPIError("JOB_CARD_NOT_FOUND", f"Job Card '{job_card_id}' was not found.")
	job_card = frappe.get_doc("Job Card", job_card_id)
	job_card.check_permission(permission)
	if job_card.docstatus == 2 or job_card.status == "Cancelled":
		raise ScannerAPIError("JOB_CARD_CANCELLED", f"Job Card '{job_card.name}' is cancelled.")
	work_order = _get_work_order(job_card.work_order)
	if not _can_use_job_card_for_purpose(job_card, work_order, PURPOSE):
		raise ScannerAPIError(
			"NO_PENDING_MATERIAL",
			f"Job Card '{job_card.name}' has no material available for transfer.",
		)
	return job_card, work_order


def _material_transfer_doc(job_card, work_order):
	"""Build the same standard Stock Entry populated by the ERPNext form."""
	doc = frappe.new_doc("Stock Entry")
	doc.purpose = PURPOSE
	doc.set_stock_entry_type()
	doc.company = work_order.company
	doc.job_card = job_card.name
	doc.work_order = work_order.name
	doc.bom_no = job_card.semi_fg_bom or job_card.bom_no or work_order.bom_no
	doc.from_bom = 1
	doc.fg_completed_qty = flt(job_card.for_quantity) - flt(job_card.transferred_qty)
	doc.from_warehouse = job_card.source_warehouse or work_order.source_warehouse
	doc.to_warehouse = job_card.wip_warehouse or work_order.wip_warehouse
	doc.get_items()
	if not doc.items:
		raise ScannerAPIError("NO_PENDING_MATERIAL", "ERPNext returned no pending raw materials.")
	# Job Card-based generation can leave row warehouses blank even though the
	# authoritative warehouses are present on the Stock Entry header.
	for row in doc.items:
		if not row.s_warehouse:
			row.s_warehouse = doc.from_warehouse
		if not row.t_warehouse:
			row.t_warehouse = doc.to_warehouse
	return doc


def _row_result(row):
	return {
		"row_name": row.name,
		"item_code": row.item_code,
		"item_name": row.item_name or frappe.db.get_value("Item", row.item_code, "item_name"),
		"quantity": flt(row.qty),
		"uom": row.uom,
		"stock_uom": row.stock_uom,
		"conversion_factor": flt(row.conversion_factor),
		"source_warehouse": row.s_warehouse,
		"target_warehouse": row.t_warehouse,
		"source_location": row.get("from_location") or "",
		"target_location": row.get("to_location") or "",
	}


@frappe.whitelist(allow_guest=True)
def get_manufacturing_job_order_context(work_order_id, mobile_token=None):
	"""Deprecated: scanner workflow now begins from a Draft Manufacture Stock Entry."""
	try:
		user = _auth(mobile_token)
		work_order = _get_work_order(_document_id(work_order_id))
		work_order.check_permission("read")
		ensure_scanner_warehouse_access(
			user,
			[work_order.source_warehouse, work_order.wip_warehouse, work_order.fg_warehouse],
		)
		cards = []
		for name in frappe.get_all("Job Card", filters={"work_order": work_order.name, "docstatus": ("!=", 2)}, pluck="name"):
			job_card = frappe.get_doc("Job Card", name)
			if _can_use_job_card_for_purpose(job_card, work_order, PURPOSE):
				cards.append(_job_card_row(job_card, PURPOSE))
		return {
			"success": True,
			"work_order": work_order.name,
			"status": work_order.status,
			"production_item": work_order.production_item,
			"item_name": frappe.db.get_value("Item", work_order.production_item, "item_name"),
			"bom_no": work_order.bom_no,
			"quantity": flt(work_order.qty),
			"produced_quantity": flt(work_order.produced_qty),
			"source_warehouse": work_order.source_warehouse,
			"wip_warehouse": work_order.wip_warehouse,
			"target_warehouse": work_order.fg_warehouse,
			"transfer_material_against": work_order.transfer_material_against,
			"job_cards": cards,
		}
	except ScannerAPIError as exc:
		return _error(exc.code, str(exc), exc.details)
	except frappe.PermissionError:
		return _error("PERMISSION_DENIED", "You do not have permission to read this Work Order.", status=403)
	except Exception as exc:
		return _error("ERP_VALIDATION_FAILED", str(exc))


@frappe.whitelist(allow_guest=True)
def get_material_transfer_context(job_card_id, mobile_token=None):
	"""Deprecated: Material Transfer is completed manually in ERPNext."""
	try:
		user = _auth(mobile_token)
		job_card, work_order = _load_job_card(job_card_id)
		doc = _material_transfer_doc(job_card, work_order)
		ensure_scanner_warehouse_access(
			user,
			[row.s_warehouse for row in doc.items] + [row.t_warehouse for row in doc.items],
		)
		return {
			"success": True,
			"operation": "material_transfer_for_manufacture",
			"job_card": job_card.name,
			"work_order": work_order.name,
			"purpose": PURPOSE,
			"source_warehouse": doc.from_warehouse,
			"target_warehouse": doc.to_warehouse,
			"items": [_row_result(row) for row in doc.items],
		}
	except ScannerAPIError as exc:
		return _error(exc.code, str(exc), exc.details)
	except frappe.PermissionError:
		return _error("PERMISSION_DENIED", "You do not have permission to read this Job Card.", status=403)
	except Exception as exc:
		return _error("ERP_VALIDATION_FAILED", str(exc))


def _apply_confirmations(doc, entries):
	if not isinstance(entries, list) or not entries:
		raise ScannerAPIError("MATERIALS_REQUIRED", "At least one material entry is required.")
	expected = {(row.item_code, row.s_warehouse, row.t_warehouse, row.uom): row for row in doc.items}
	seen = set()
	for index, entry in enumerate(entries, 1):
		key = tuple(str(entry.get(field) or "").strip() for field in ("item_code", "source_warehouse", "target_warehouse", "uom"))
		if key in seen:
			raise ScannerAPIError("DUPLICATE_MATERIAL", f"Entry #{index} duplicates another material row.")
		seen.add(key)
		row = expected.get(key)
		if not row:
			raise ScannerAPIError("MATERIAL_MISMATCH", f"Entry #{index} does not match an ERPNext pending material row.")
		quantity = flt(entry.get("quantity"))
		if not math.isfinite(quantity) or quantity <= 0 or not math.isclose(quantity, flt(row.qty), abs_tol=1e-9, rel_tol=0):
			raise ScannerAPIError("QUANTITY_MISMATCH", f"Entry #{index}: expected {flt(row.qty):g} {row.uom} for {row.item_code}.")
		batch_no = str(entry.get("batch_no") or "").strip()
		serial_numbers = entry.get("serial_numbers") or []
		if batch_no:
			if not frappe.db.exists("Batch", {"name": batch_no, "item": row.item_code}):
				raise ScannerAPIError("INVALID_BATCH", f"Batch '{batch_no}' is invalid for {row.item_code}.")
			row.batch_no = batch_no
		if serial_numbers:
			row.serial_no = "\n".join(serial_numbers)
	if set(expected) != seen:
		raise ScannerAPIError("MATERIALS_INCOMPLETE", "All ERPNext pending material rows must be confirmed.")


@frappe.whitelist(allow_guest=True)
def submit_material_transfer(job_card_id, operation, submission_id, entries, mobile_token=None):
	"""Deprecated: Material Transfer is completed manually in ERPNext."""
	savepoint_created = False
	try:
		user = _auth(mobile_token)
		if operation != "material_transfer_for_manufacture":
			raise ScannerAPIError("INVALID_OPERATION", "operation must be material_transfer_for_manufacture.")
		if isinstance(entries, str):
			entries = json.loads(entries)
		job_card_id, submission_id = _document_id(job_card_id), _uuid(submission_id)
		request_json, request_hash = _canonical(job_card_id, submission_id, entries)
		replay = frappe.db.get_value("Material Transfer Scanner Submission", submission_id, ["request_hash", "result_json"], as_dict=True)
		if replay:
			if replay.request_hash != request_hash:
				raise ScannerAPIError("DUPLICATE_SUBMISSION_CONFLICT", "submission_id was reused with different content.")
			result = json.loads(replay.result_json)
			result["duplicate_submission"] = True
			return result

		frappe.db.savepoint("scanner_material_transfer")
		savepoint_created = True
		frappe.db.sql("select name from `tabJob Card` where name=%s for update", job_card_id)
		# A concurrent request may have completed while this request waited for the
		# Job Card lock. Re-check durable idempotency before generating stock movement.
		replay = frappe.db.get_value("Material Transfer Scanner Submission", submission_id, ["request_hash", "result_json"], as_dict=True)
		if replay:
			if replay.request_hash != request_hash:
				raise ScannerAPIError("DUPLICATE_SUBMISSION_CONFLICT", "submission_id was reused with different content.")
			result = json.loads(replay.result_json)
			result["duplicate_submission"] = True
			return result
		job_card, work_order = _load_job_card(job_card_id, "write")
		frappe.has_permission("Stock Entry", ptype="create", throw=True)
		doc = _material_transfer_doc(job_card, work_order)
		ensure_scanner_warehouse_access(
			user,
			[row.s_warehouse for row in doc.items] + [row.t_warehouse for row in doc.items],
			require_transact=True,
		)
		_apply_confirmations(doc, entries)
		doc.insert()
		doc.submit()
		result = {
			"success": True,
			"operation": operation,
			"submission_id": submission_id,
			"duplicate_submission": False,
			"stock_entry_id": doc.name,
			"docstatus": doc.docstatus,
			"job_card": job_card.name,
			"work_order": work_order.name,
			"item_count": len(doc.items),
			"transferred_items": [_row_result(row) for row in doc.items],
		}
		# This is an API-owned immutable idempotency record, not a document the
		# scanner user creates directly. The caller's Stock Entry permissions were
		# already enforced above; persist this internal record as the system.
		frappe.get_doc({
			"doctype": "Material Transfer Scanner Submission",
			"submission_id": submission_id,
			"job_card": job_card.name,
			"work_order": work_order.name,
			"stock_entry": doc.name,
			"processed_by": user,
			"processed_at": now_datetime(),
			"request_hash": request_hash,
			"request_json": request_json,
			"result_json": json.dumps(result, separators=(",", ":")),
			"status": "Success",
		}).insert(ignore_permissions=True)
		frappe.db.commit()
		return result
	except ScannerAPIError as exc:
		if savepoint_created:
			frappe.db.rollback(save_point="scanner_material_transfer")
		return _error(exc.code, str(exc), exc.details, 409 if exc.code == "DUPLICATE_SUBMISSION_CONFLICT" else 400)
	except frappe.PermissionError:
		if savepoint_created:
			frappe.db.rollback(save_point="scanner_material_transfer")
		return _error("PERMISSION_DENIED", "You do not have permission to create this Stock Entry.", status=403)
	except Exception as exc:
		if savepoint_created:
			frappe.db.rollback(save_point="scanner_material_transfer")
		return _error("ERP_VALIDATION_FAILED", str(exc))
