import hashlib
import json
import uuid

import frappe
from frappe.utils import now_datetime

from qcmc_logic.api.stock_reconciliation import _authenticate_request_user


class WorkflowError(frappe.ValidationError):
	def __init__(self, code, message, details=None, status=400):
		self.code = code
		self.details = details or {}
		self.status = status
		super().__init__(message)


def error_response(exc):
	frappe.local.response["http_status_code"] = getattr(exc, "status", 400)
	return {
		"success": False,
		"error_code": getattr(exc, "code", "ERP_VALIDATION_FAILED"),
		"message": str(exc),
		**({"details": exc.details} if getattr(exc, "details", None) else {}),
	}


def authenticated_user(mobile_token=None):
	user = _authenticate_request_user(mobile_token)
	if not user or user == "Guest":
		raise WorkflowError("PERMISSION_DENIED", "Session expired. Please log in again.", status=403)
	return user


def active_employee(user):
	if user == "Administrator":
		return frappe._dict(name="Administrator", user_id=user, employee_name="Administrator")
	employee = frappe.db.get_value(
		"Employee", {"user_id": user, "status": "Active"},
		["name", "user_id", "employee_name"], as_dict=True,
	)
	if not employee:
		raise WorkflowError("PERMISSION_DENIED", "No active Employee is linked to this account.", status=403)
	return employee


def require_role(user, role, code):
	if user != "Administrator" and role not in frappe.get_roles(user):
		raise WorkflowError(code, f"The authenticated employee does not have the {role} role.", status=403)


def parse_json(value, default=None):
	if value in (None, ""):
		return default
	if isinstance(value, (dict, list)):
		return value
	try:
		return json.loads(value)
	except (TypeError, ValueError):
		raise WorkflowError("ERP_VALIDATION_FAILED", "The request contains invalid JSON.")


def request_uuid(value, fieldname="request_id"):
	value = str(value or "").strip()
	if not value:
		raise WorkflowError("REQUEST_ID_REQUIRED", f"{fieldname} is required.")
	try:
		return str(uuid.UUID(value))
	except (TypeError, ValueError):
		raise WorkflowError("ERP_VALIDATION_FAILED", f"{fieldname} must be a valid UUID.")


def canonical_hash(payload):
	text = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
	return hashlib.sha256(text.encode()).hexdigest(), text


def begin_request(operation, request_id, payload, user):
	request_id = request_uuid(request_id)
	request_hash, request_json = canonical_hash(payload)
	existing = frappe.db.get_value(
		"Warehouse Workflow Request", request_id,
		["operation", "request_hash", "response_json"], as_dict=True,
	)
	if existing:
		if existing.operation != operation or existing.request_hash != request_hash:
			raise WorkflowError("DUPLICATE_TRANSACTION", "This request ID was already used with different content.")
		response = json.loads(existing.response_json)
		response["duplicate_request"] = True
		return frappe._dict(name=request_id, replay=response)
	return frappe._dict(
		name=request_id, operation=operation, request_hash=request_hash,
		request_json=request_json, user=user, replay=None,
	)


def finish_request(request, response):
	frappe.get_doc({
		"doctype": "Warehouse Workflow Request",
		"request_id": request.name,
		"operation": request.operation,
		"request_hash": request.request_hash,
		"request_json": request.request_json,
		"response_json": json.dumps(response, default=str, separators=(",", ":")),
		"processed_by": request.user,
		"processed_at": now_datetime(),
	}).insert(ignore_permissions=True)
	return response
