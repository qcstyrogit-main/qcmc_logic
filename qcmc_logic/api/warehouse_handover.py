import json
import secrets
import uuid
from datetime import timedelta
from decimal import Decimal, InvalidOperation

import frappe
from frappe.utils import flt, get_datetime, now_datetime

from qcmc_logic.api.stock_entry_scanner import _purpose
from qcmc_logic.api.warehouse_workflow import (
	WorkflowError, active_employee, authenticated_user, begin_request,
	error_response, finish_request, parse_json, require_role,
)
from qcmc_logic.utils import ensure_scanner_warehouse_access, get_user_allowed_warehouses


TOKEN_TTL_HOURS = 24
VERIFIED_HANDOVER_STATUSES = {"CHECKED", "ALLOCATION_CREATED"}


def _decimal(value, fieldname="quantity"):
	try:
		value = Decimal(str(value).replace(",", ""))
	except (InvalidOperation, TypeError, ValueError):
		raise WorkflowError("INVALID_QUANTITY", f"{fieldname} must be numeric.")
	if not value.is_finite() or value < 0:
		raise WorkflowError("INVALID_QUANTITY", f"{fieldname} must be non-negative.")
	return value


def _draft_stock_entry(name, user, mutate=False):
	if not frappe.db.exists("Stock Entry", name):
		raise WorkflowError("SOURCE_DOCUMENT_NOT_FOUND", f"Stock Entry '{name}' was not found.")
	doc = frappe.get_doc("Stock Entry", name)
	if doc.docstatus != 0:
		raise WorkflowError("SOURCE_DOCUMENT_NOT_DRAFT", f"Stock Entry '{name}' is not Draft.")
	if _purpose(doc) != "Manufacture":
		raise WorkflowError("INVALID_TRANSACTION_TYPE", f"Stock Entry '{name}' is not a Manufacture entry.")
	warehouses = [row.t_warehouse for row in (doc.get("items") or []) if row.is_finished_item and row.t_warehouse]
	try:
		ensure_scanner_warehouse_access(user, warehouses, require_transact=mutate)
	except frappe.PermissionError:
		raise WorkflowError("WAREHOUSE_PERMISSION_DENIED", "Warehouse permission denied.", status=403)
	return doc


def _source_rows(doc):
	rows = []
	for row in doc.get("items") or []:
		if not row.is_finished_item or not row.t_warehouse:
			continue
		stock_qty = Decimal(str(row.qty or 0))
		item = frappe.db.get_value("Item", row.item_code, ["item_name", "stock_uom"], as_dict=True) or {}
		rows.append({
			"stock_entry": doc.name,
			"stock_entry_row": row.name,
			"job_card": doc.get("custom_final_job_card") or doc.job_card or "",
			"work_order": doc.work_order or "",
			"pull_out_slip": doc.get("custom_reference_document") or "",
			"item": row.item_code,
			"item_name": item.get("item_name") or row.item_name or row.item_code,
			"recorded_quantity": stock_qty,
			"verified_quantity": stock_qty,
			"stock_uom": item.get("stock_uom") or row.stock_uom,
			"source_modified": doc.modified,
		})
	if not rows:
		raise WorkflowError("ERP_VALIDATION_FAILED", f"Stock Entry '{doc.name}' has no finished-item row.")
	return rows


def _get_batch(batch_id, user, token=None, mutate=False):
	if not batch_id or not frappe.db.exists("Scanner Warehouse Handover", batch_id):
		raise WorkflowError("HANDOVER_NOT_FOUND", "The handover batch does not exist.")
	batch = frappe.get_doc("Scanner Warehouse Handover", batch_id)
	if batch.status in {"CANCELLED", "COMPLETED"}:
		raise WorkflowError("INVALID_HANDOVER_QR", f"Handover {batch.name} is {batch.status}.")
	if token is not None:
		stored = batch.get_password("generated_qr_token", raise_exception=False) or ""
		if not stored or not secrets.compare_digest(stored, str(token or "")):
			raise WorkflowError("INVALID_HANDOVER_QR", "The handover QR token is invalid.")
		if not batch.qr_expires_at or get_datetime(batch.qr_expires_at) < now_datetime():
			raise WorkflowError("INVALID_HANDOVER_QR", "The handover QR token has expired.")
	warehouses = []
	for source in batch.source_stock_entries:
		doc = _draft_stock_entry(source.stock_entry, user, mutate=mutate)
		warehouses.extend(row.t_warehouse for row in (doc.get("items") or []) if row.is_finished_item and row.t_warehouse)
	try:
		ensure_scanner_warehouse_access(user, warehouses, require_transact=mutate)
	except frappe.PermissionError:
		raise WorkflowError("WAREHOUSE_PERMISSION_DENIED", "Warehouse permission denied.", status=403)
	return batch


def _employee_name(employee):
	if not employee:
		return ""
	return frappe.db.get_value("Employee", employee, "employee_name") or employee


def _assign_checker_name(assign_checker):
	if not assign_checker:
		return ""
	return frappe.db.get_value("Assign Checker", assign_checker, "checker_name") or ""


def _unambiguous_job_card(work_order):
	if not work_order:
		return ""
	rows = frappe.get_all(
		"Job Card",
		filters={"work_order": work_order, "docstatus": ["!=", 2]},
		pluck="name",
		limit_page_length=2,
	)
	return rows[0] if len(rows) == 1 else ""


def _job_card_for_source(doc, stock_row, source):
	direct = str(doc.get("job_card") or doc.get("custom_final_job_card") or "").strip()
	if direct:
		return direct
	row_link = str(stock_row.get("job_card") or stock_row.get("custom_final_job_card") or "").strip()
	if row_link:
		return row_link
	stored = str(source.get("job_card") or "").strip()
	if stored:
		return stored
	return _unambiguous_job_card(doc.get("work_order"))


def _batch_response(batch, user=None):
	"""Return current ERP documents grouped by Stock Entry.

	The child table preserves checker quantities and durable source links, while
	all display metadata is refreshed from the authoritative Draft Stock Entry.
	"""
	grouped = []
	flat_sources = []
	for stock_entry_id in dict.fromkeys(row.stock_entry for row in batch.source_stock_entries):
		doc = _draft_stock_entry(stock_entry_id, user, mutate=False) if user else frappe.get_doc("Stock Entry", stock_entry_id)
		source_rows = [row for row in batch.source_stock_entries if row.stock_entry == stock_entry_id]
		items = []
		for source in source_rows:
			stock_row = next((row for row in (doc.get("items") or []) if row.name == source.stock_entry_row), None)
			if not stock_row or not stock_row.is_finished_item:
				raise WorkflowError("SOURCE_DOCUMENT_CHANGED", f"Finished-item row '{source.stock_entry_row}' no longer exists in Stock Entry '{doc.name}'.")
			item_name = stock_row.item_name or frappe.db.get_value("Item", stock_row.item_code, "item_name") or stock_row.item_code
			item = {
				"stock_entry_id": doc.name,
				"stock_entry_row": stock_row.name,
				"item_code": stock_row.item_code,
				"item_name": item_name,
				"recorded_quantity": flt(stock_row.qty),
				"verified_quantity": flt(source.verified_quantity if source.verified_quantity is not None else stock_row.qty),
				"stock_uom": stock_row.stock_uom or source.stock_uom,
				"modified": str(doc.modified),
			}
			items.append(item)
			flat_sources.append({
				"stock_entry_id": doc.name,
				"stock_entry_row": stock_row.name,
				"job_card_id": _job_card_for_source(doc, stock_row, source),
				"work_order_id": doc.work_order or source.work_order or "",
				"pull_out_slip": doc.get("custom_reference_document") or source.pull_out_slip or "",
				**item,
				"uom": item["stock_uom"],
				"expected_modified": str(doc.modified),
			})
		first_source = source_rows[0]
		first_row = next(row for row in (doc.get("items") or []) if row.name == first_source.stock_entry_row)
		grouped.append({
			"stock_entry_id": doc.name,
			"docstatus": doc.docstatus,
			"status": "Draft" if doc.docstatus == 0 else doc.get("status") or "",
			"job_card_id": _job_card_for_source(doc, first_row, first_source),
			"work_order_id": doc.work_order or first_source.work_order or "",
			"custom_reference_document": doc.get("custom_reference_document") or first_source.pull_out_slip or "",
			"modified": str(doc.modified),
			"items": items,
		})

	return {
		"success": True,
		"batch_id": batch.name,
		"status": batch.status,
		"warehouse_man": _employee_name(batch.warehouse_man),
		"warehouse_man_id": batch.warehouse_man,
		"checker": _assign_checker_name(batch.checker),
		"checker_id": batch.checker or "",
		"checker_employee": batch.get("checker_employee") or "",
		"verified_at": get_datetime(batch.checked_at).isoformat() if batch.checked_at else "",
		"picker": _employee_name(batch.picker),
		"picker_id": batch.picker or "",
		"stock_entry_ids": list(dict.fromkeys(row.stock_entry for row in batch.source_stock_entries)),
		"source_stock_entries": grouped,
		"sources": flat_sources,
	}


def _audit(event_type, batch, request_id=None, **values):
	data = {
		"doctype": "Warehouse Workflow Audit", "event_id": str(uuid.uuid4()),
		"event_type": event_type, "handover": batch.name,
		"warehouse_man": batch.warehouse_man,
		"checker": batch.get("checker_employee"),
		"assign_checker": batch.checker,
		"picker": batch.picker, "event_timestamp": now_datetime(),
		"request_id": request_id,
	}
	data.update(values)
	frappe.get_doc(data).insert(ignore_permissions=True)


@frappe.whitelist(allow_guest=True)
def add_stock_entry(stock_entry_id, request_id, batch_id=None, device_id=None, mobile_token=None):
	try:
		user = authenticated_user(mobile_token)
		employee = active_employee(user)
		request = begin_request("handover.add_stock_entry", request_id, {
			"batch_id": batch_id or "", "stock_entry_id": stock_entry_id,
			"device_id": device_id or "",
		}, user)
		if request.replay is not None:
			replay_batch_id = request.replay.get("batch_id")
			batch = _get_batch(replay_batch_id, user) if replay_batch_id else None
			if not batch:
				return request.replay
			response = _batch_response(batch, user)
			response.update({"duplicate_request": True, "request_id": request.name})
			return response
		doc = _draft_stock_entry(stock_entry_id, user, mutate=True)
		rows = _source_rows(doc)
		if batch_id:
			batch = _get_batch(batch_id, user, mutate=True)
			if batch.warehouse_man != employee.name and user != "Administrator":
				raise WorkflowError("PERMISSION_DENIED", "Only the batch Warehouse Man may add source entries.", status=403)
			if batch.status not in {"OPEN", "PENDING_CHECK"}:
				raise WorkflowError("INVALID_HANDOVER_STATUS", "This handover no longer accepts source entries.")
			if batch.company != doc.company:
				raise WorkflowError("ERP_VALIDATION_FAILED", "All handover sources must belong to one company.")
		else:
			batch = frappe.get_doc({
				"doctype": "Scanner Warehouse Handover", "status": "OPEN",
				"company": doc.company, "warehouse_man": employee.name,
				"device_id": str(device_id or "").strip(), "created_at": now_datetime(),
			})
		seen = {(row.stock_entry, row.stock_entry_row) for row in batch.source_stock_entries}
		for row in rows:
			if (row["stock_entry"], row["stock_entry_row"]) not in seen:
				batch.append("source_stock_entries", row)
		batch.status = "PENDING_CHECK"
		# Any previously printed QR represented an older batch membership.
		batch.generated_qr_token = ""
		batch.qr_expires_at = None
		batch.save(ignore_permissions=True)
		_audit("SOURCE_ADDED", batch, request.name, source_doctype="Stock Entry", source_document=doc.name, device_id=device_id)
		response = _batch_response(batch, user)
		response["duplicate_request"] = False
		return finish_request(request, response)
	except WorkflowError as exc:
		return error_response(exc)
	except frappe.PermissionError:
		return error_response(WorkflowError("PERMISSION_DENIED", "Warehouse access denied.", status=403))
	except Exception as exc:
		frappe.log_error(frappe.get_traceback(), "warehouse_handover.add_stock_entry")
		return error_response(WorkflowError("ERP_VALIDATION_FAILED", str(exc)))


@frappe.whitelist(allow_guest=True)
def generate_handover_qr_payload(batch_id, request_id=None, mobile_token=None):
	try:
		user = authenticated_user(mobile_token)
		request = begin_request(
			"handover.generate_handover_qr_payload", request_id,
			{"batch_id": batch_id}, user,
		) if request_id else None
		if request and request.replay is not None:
			return request.replay
		batch = _get_batch(batch_id, user)
		# Allocation creation advances a verified batch from CHECKED to
		# ALLOCATION_CREATED. Keep QR regeneration available after that normal
		# transition, while still requiring the persisted checker verification.
		if batch.status not in VERIFIED_HANDOVER_STATUSES or not batch.checker:
			raise WorkflowError("CHECKER_VERIFICATION_REQUIRED", "Checker Verification is required before generating the Handover QR.")
		if not frappe.db.exists("Assign Checker", batch.checker):
			raise WorkflowError("CHECKER_VERIFICATION_REQUIRED", "The verified Assign Checker no longer exists.")
		stock_entry_ids = list(dict.fromkeys(row.stock_entry for row in batch.source_stock_entries))
		if not stock_entry_ids:
			raise WorkflowError("ERP_VALIDATION_FAILED", "The handover has no source Stock Entries.")
		for stock_entry_id in stock_entry_ids:
			doc = _draft_stock_entry(stock_entry_id, user)
			if doc.get("custom_verified_by") != batch.checker:
				raise WorkflowError("CHECKER_VERIFICATION_REQUIRED", "All Draft Stock Entries must be verified by the batch Checker before generating the Handover QR.")
		token = secrets.token_urlsafe(32)
		batch.generated_qr_token = token
		batch.qr_expires_at = now_datetime() + timedelta(hours=TOKEN_TTL_HOURS)
		batch.save(ignore_permissions=True)
		response = {
			"success": True, "type": "QCMC_WAREHOUSE_HANDOVER", "version": 1,
			"batch_id": batch.name,
			"stock_entry_ids": stock_entry_ids,
			"issued_at": now_datetime().isoformat(), "expires_at": get_datetime(batch.qr_expires_at).isoformat(),
			"token": token,
		}
		return finish_request(request, response) if request else response
	except WorkflowError as exc:
		return error_response(exc)
	except Exception as exc:
		return error_response(WorkflowError("ERP_VALIDATION_FAILED", str(exc)))


@frappe.whitelist(allow_guest=True)
def generate_handover_qr(batch_id, request_id=None, mobile_token=None):
	"""Compatibility alias for Scanner clients using the shorter method name."""
	return generate_handover_qr_payload(batch_id, request_id=request_id, mobile_token=mobile_token)


@frappe.whitelist(allow_guest=True)
def get_checker_review(batch_id, token, mobile_token=None):
	try:
		user = authenticated_user(mobile_token)
		require_role(user, "Warehouse Checker", "CHECKER_NOT_AUTHORIZED")
		batch = _get_batch(batch_id, user, token=token)
		return _batch_response(batch, user)
	except WorkflowError as exc:
		return error_response(exc)


@frappe.whitelist(allow_guest=True)
def update_checked_quantities(batch_id, request_id, rows, mobile_token=None, device_id=None):
	try:
		user = authenticated_user(mobile_token)
		checker = active_employee(user)
		rows = parse_json(rows, [])
		request = begin_request("handover.update_checked_quantities", request_id, {"batch_id": batch_id, "rows": rows}, user)
		if request.replay is not None:
			return request.replay
		batch = _get_batch(batch_id, user, mutate=True)
		if batch.status not in {"PENDING_CHECK", "OPEN"}:
			raise WorkflowError("INVALID_HANDOVER_STATUS", "Checked quantities can no longer be changed.")
		sources = {(row.stock_entry, row.stock_entry_row): row for row in batch.source_stock_entries}
		for submitted in rows:
			key = (str(submitted.get("stock_entry_id") or ""), str(submitted.get("stock_entry_row") or ""))
			source = sources.get(key)
			if not source or submitted.get("item_code") != source.item:
				raise WorkflowError("ERP_VALIDATION_FAILED", "A checked row does not belong to this handover.")
			doc = _draft_stock_entry(source.stock_entry, user, mutate=True)
			if str(doc.modified) != str(submitted.get("expected_modified") or source.source_modified):
				raise WorkflowError("SOURCE_DOCUMENT_CHANGED", f"Stock Entry '{doc.name}' changed after it was loaded.")
			item = frappe.db.get_value("Item", source.item, ["stock_uom"], as_dict=True) or {}
			if str(submitted.get("uom") or "").strip() != str(item.get("stock_uom") or source.stock_uom):
				raise WorkflowError("INVALID_QUANTITY", "The checked UOM must match the Item Stock UOM.")
			verified = _decimal(submitted.get("verified_quantity"), "verified_quantity")
			original = Decimal(str(source.recorded_quantity))
			reason = str(submitted.get("reason") or "").strip()
			if verified != original and not reason:
				raise WorkflowError("ERP_VALIDATION_FAILED", "A correction reason is required when quantity changes.")
			stock_row = next((row for row in (doc.get("items") or []) if row.name == source.stock_entry_row), None)
			if not stock_row or stock_row.item_code != source.item:
				raise WorkflowError("SOURCE_DOCUMENT_CHANGED", "The finished-item row changed after handover creation.")
			factor = Decimal(str(stock_row.conversion_factor or 1))
			stock_row.qty = verified / factor
			stock_row.transfer_qty = verified
			doc.save(ignore_permissions=True)
			source.verified_quantity = verified
			source.source_modified = doc.modified
			source.verification_modified = doc.modified
			_audit("CHECKER_QUANTITY_CORRECTED" if verified != original else "CHECKER_QUANTITY_CONFIRMED", batch, None,
				source_doctype="Stock Entry", source_document=doc.name, source_row=stock_row.name,
				item_code=source.item, original_quantity=original, actual_quantity=verified,
				stock_uom=source.stock_uom, checker=checker.name, device_id=device_id, reason=reason)
		batch.save(ignore_permissions=True)
		return finish_request(request, _batch_response(batch, user))
	except WorkflowError as exc:
		return error_response(exc)
	except Exception as exc:
		frappe.log_error(frappe.get_traceback(), "warehouse_handover.update_checked_quantities")
		return error_response(WorkflowError("ERP_VALIDATION_FAILED", str(exc)))


def _resolve_checker_qr(value, authenticated_checker_user=None):
	"""Resolve a compact Assign Checker QR using its authoritative document ID."""
	value = str(value or "").strip()
	if not value.startswith("{"):
		raise WorkflowError("INVALID_CHECKER_QR", "Scan the complete Assign Checker QR code; plain checker names are not accepted.", status=403)
	payload = parse_json(value, {})
	assign_checker_id = str(payload.get("doc_name") or "").strip()
	if not assign_checker_id:
		raise WorkflowError("INVALID_CHECKER_QR", "The Assign Checker QR is incomplete.", status=403)
	if not frappe.db.exists("Assign Checker", assign_checker_id):
		raise WorkflowError("INVALID_CHECKER_QR", "The Assign Checker QR does not exist.", status=403)
	record = frappe.get_doc("Assign Checker", assign_checker_id)
	if record.disabled:
		raise WorkflowError("INVALID_CHECKER_QR", "The Assign Checker QR is disabled.", status=403)
	if record.employee:
		employee = frappe.db.get_value(
			"Employee", {"name": record.employee, "status": "Active"},
			["name", "user_id", "employee_name"], as_dict=True,
		)
		if not employee:
			raise WorkflowError("CHECKER_NOT_AUTHORIZED", "The Employee linked to this Assign Checker is inactive.", status=403)
	else:
		employee = None
	return frappe._dict(assign_checker=record, employee=employee)


def _resolve_employee_qr(value):
	"""Legacy wrapper for backward compatibility."""
	return _resolve_checker_qr(value)


@frappe.whitelist(allow_guest=True)
def confirm_checker(batch_id, checker_qr, request_id, mobile_token=None, device_id=None):
	"""Atomically verify every Draft source using an Assign Checker QR."""
	savepoint_started = False
	try:
		user = authenticated_user(mobile_token)
		request = begin_request(
			"handover.confirm_checker",
			request_id,
			{"batch_id": batch_id, "checker_qr": checker_qr},
			user
		)
		if request.replay is not None:
			return request.replay
		batch = _get_batch(batch_id, user, mutate=True)
		if not batch.source_stock_entries:
			raise WorkflowError("ERP_VALIDATION_FAILED", "The handover has no linked Stock Entries.")
		verified = _resolve_checker_qr(checker_qr, authenticated_checker_user=user)
		assign_checker = verified.assign_checker
		checker = verified.employee

		if checker and checker.name == batch.warehouse_man and user != "Administrator":
			raise WorkflowError(
				"CHECKER_NOT_AUTHORIZED",
				"The Warehouse Man cannot confirm the same handover as Checker.",
				status=403
			)
		
		if batch.checker:
			if batch.checker != assign_checker.name:
				raise WorkflowError("CHECKER_VERIFICATION_CONFLICT", "This handover was already verified by a different Checker.", status=409)
			response = _batch_response(batch, user)
			response.update({
				"status": "CHECKED", "checker": assign_checker.checker_name,
				"checker_id": assign_checker.name,
				"verified_at": get_datetime(batch.checked_at).isoformat() if batch.checked_at else "",
			})
			return finish_request(request, response)

		documents = {}
		for source in batch.source_stock_entries:
			doc = documents.get(source.stock_entry) or _draft_stock_entry(source.stock_entry, user, mutate=True)
			documents[doc.name] = doc
			if str(doc.modified) != str(source.source_modified):
				raise WorkflowError(
					"SOURCE_DOCUMENT_CHANGED",
					f"Stock Entry '{doc.name}' changed after Checker review.",
				)
			stock_row = next((row for row in (doc.get("items") or []) if row.name == source.stock_entry_row), None)
			if not stock_row or not stock_row.is_finished_item or flt(source.verified_quantity) < 0:
				raise WorkflowError("ERP_VALIDATION_FAILED", f"Handover quantity validation is unresolved for Stock Entry '{doc.name}'.")

		frappe.db.savepoint("confirm_checker")
		savepoint_started = True
		verified_at = now_datetime()
		previous_status = batch.status
		for doc in documents.values():
			if doc.get("custom_verified_by") and doc.get("custom_verified_by") != assign_checker.name:
				raise WorkflowError("CHECKER_VERIFICATION_CONFLICT", f"Stock Entry '{doc.name}' was already verified by a different Checker.", status=409)
			doc.custom_verified_by = assign_checker.name
			doc.save(ignore_permissions=True)
			if doc.docstatus != 0:
				raise WorkflowError("SOURCE_DOCUMENT_NOT_DRAFT", f"Stock Entry '{doc.name}' must remain Draft.")
			for source in batch.source_stock_entries:
				if source.stock_entry == doc.name:
					source.source_modified = doc.modified
					source.verification_modified = doc.modified

		batch.checker = assign_checker.name
		batch.checker_employee = checker.name if checker else ""
		batch.verified_by_user = user
		batch.checked_at = verified_at
		batch.device_id = str(device_id or "").strip()
		batch.checker_verification_id = str(uuid.uuid4())
		batch.status = "CHECKED"
		batch.save(ignore_permissions=True)
		_audit(
			"CHECKER_CONFIRMED",
			batch,
			request.name,
			checker=checker.name if checker else None,
			assign_checker=assign_checker.name,
			checker_name=assign_checker.checker_name,
			authenticated_user=user,
			previous_status=previous_status,
			new_status="CHECKED",
			device_id=device_id,
			details_json=json.dumps({"stock_entry_ids": list(documents), "verified_at": verified_at.isoformat()}, separators=(",", ":")),
		)
		response = _batch_response(batch, user)
		response.update({
			"status": "CHECKED", "checker": assign_checker.checker_name,
			"checker_id": assign_checker.name, "verified_at": verified_at.isoformat(),
			"stock_entry_ids": list(documents),
		})
		return finish_request(request, response)
	except WorkflowError as exc:
		if savepoint_started:
			frappe.db.rollback(save_point="confirm_checker")
		return error_response(exc)
	except Exception as exc:
		if savepoint_started:
			frappe.db.rollback(save_point="confirm_checker")
		frappe.log_error(frappe.get_traceback(), "warehouse_handover.confirm_checker")
		return error_response(WorkflowError("ERP_VALIDATION_FAILED", str(exc)))


@frappe.whitelist(allow_guest=True)
def get_picker_context(batch_id, token, mobile_token=None):
	try:
		user = authenticated_user(mobile_token)
		require_role(user, "Warehouse Picker", "PICKER_NOT_AUTHORIZED")
		batch = _get_batch(batch_id, user, token=token)
		response = _batch_response(batch, user)
		response.update({
			"transaction_types": ["Stock Entry", "Warehouse Transfer", "Warehouse Receiving Report", "Delivery Note", "Sales Invoice"],
			"available_transaction_types": ["Stock Entry", "Warehouse Transfer", "Warehouse Receiving Report", "Delivery Note", "Sales Invoice"],
			"permitted_warehouses": get_user_allowed_warehouses(user, require_transact=True, source="Role Profile"),
			"required_fields": {"Stock Entry": ["warehouse", "posting_date", "posting_time"]},
		})
		return response
	except WorkflowError as exc:
		return error_response(exc)
