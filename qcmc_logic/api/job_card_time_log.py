import math

import frappe
from frappe.utils import flt, now_datetime

from qcmc_logic.api.stock_entry_scanner import ScannerAPIError, _auth, _error


def _document_id(value):
	return str(value or "").strip().rstrip("/").rsplit("/", 1)[-1]


def _load_job_card(job_card_id, permission="read"):
	job_card_id = _document_id(job_card_id)
	if not frappe.db.exists("Job Card", job_card_id):
		raise ScannerAPIError("JOB_CARD_NOT_FOUND", f"Job Card '{job_card_id}' was not found.")
	doc = frappe.get_doc("Job Card", job_card_id)
	doc.check_permission(permission)
	if doc.docstatus == 2 or doc.status == "Cancelled":
		raise ScannerAPIError("JOB_CARD_CANCELLED", f"Job Card '{doc.name}' is cancelled.")
	if doc.docstatus == 1:
		raise ScannerAPIError("JOB_CARD_SUBMITTED", f"Job Card '{doc.name}' is already submitted.")
	return doc


def _employee(employee, user, company):
	employee = str(employee or "").strip()
	if not employee:
		employee = frappe.db.get_value(
			"Employee", {"user_id": user, "status": "Active"}, "name"
		)
	if not employee:
		raise ScannerAPIError(
			"EMPLOYEE_REQUIRED",
			"employee is required because the scanner user is not linked to an active Employee.",
		)
	row = frappe.db.get_value(
		"Employee", employee, ["name", "employee_name", "status", "company"], as_dict=True
	)
	if not row or row.status != "Active":
		raise ScannerAPIError("INVALID_EMPLOYEE", f"Employee '{employee}' does not exist or is not active.")
	if row.company and company and row.company != company:
		raise ScannerAPIError(
			"EMPLOYEE_COMPANY_MISMATCH",
			f"Employee '{employee}' does not belong to {company}.",
		)
	return row


def _time_log(row):
	return {
		"time_log_id": row.name,
		"employee": row.employee or "",
		"employee_name": frappe.db.get_value("Employee", row.employee, "employee_name") if row.employee else "",
		"from_time": str(row.from_time or ""),
		"to_time": str(row.to_time or ""),
		"time_in_mins": flt(row.time_in_mins),
		"completed_qty": flt(row.completed_qty),
	}


def _context(doc, duplicate_request=False, affected_row=None):
	item_name = frappe.db.get_value("Item", doc.production_item, "item_name")
	result = {
		"success": True,
		"job_card_id": doc.name,
		"work_order_id": doc.work_order,
		"status": doc.status,
		"operation": doc.operation,
		"item_code": doc.production_item,
		"item_name": item_name or "",
		"uom": frappe.db.get_value("Item", doc.production_item, "stock_uom") or "",
		"quantity_to_manufacture": flt(doc.for_quantity),
		"total_completed_qty": flt(doc.total_completed_qty),
		"total_time_in_mins": flt(doc.total_time_in_mins),
		"actual_start_date": str(doc.actual_start_date or ""),
		"started_without_time_log": bool(
			doc.status == "Work In Progress" and doc.actual_start_date and not doc.time_logs
		),
		"duplicate_request": duplicate_request,
		"time_logs": [_time_log(row) for row in doc.time_logs],
	}
	if affected_row:
		result["time_log"] = _time_log(affected_row)
	return result


@frappe.whitelist(allow_guest=True)
def get_job_card_time_context(job_card_id, mobile_token=None):
	try:
		_auth(mobile_token)
		return _context(_load_job_card(job_card_id))
	except ScannerAPIError as exc:
		return _error(exc.code, str(exc), exc.details, 403 if exc.code == "PERMISSION_DENIED" else 400)
	except frappe.PermissionError:
		return _error("PERMISSION_DENIED", "You do not have permission to read this Job Card.", status=403)
	except Exception as exc:
		return _error("ERP_VALIDATION_FAILED", str(exc))


@frappe.whitelist(allow_guest=True)
def start_job_card_time(job_card_id, employee=None, mobile_token=None):
	try:
		user = _auth(mobile_token)
		job_card_id = _document_id(job_card_id)
		frappe.db.sql("select name from `tabJob Card` where name=%s for update", job_card_id)
		doc = _load_job_card(job_card_id, "write")
		employee_row = _employee(employee, user, doc.company)
		open_rows = [row for row in doc.time_logs if row.employee == employee_row.name and not row.to_time]
		if open_rows:
			return _context(doc, duplicate_request=True, affected_row=open_rows[-1])

		row = doc.append(
			"time_logs",
			{"employee": employee_row.name, "from_time": now_datetime(), "completed_qty": 0},
		)
		doc.status = "Work In Progress"
		doc.save()
		frappe.db.commit()
		return _context(doc, affected_row=row)
	except ScannerAPIError as exc:
		frappe.db.rollback()
		return _error(exc.code, str(exc), exc.details, 403 if exc.code == "PERMISSION_DENIED" else 400)
	except frappe.PermissionError:
		frappe.db.rollback()
		return _error("PERMISSION_DENIED", "You do not have permission to update this Job Card.", status=403)
	except Exception as exc:
		frappe.db.rollback()
		return _error("ERP_VALIDATION_FAILED", str(exc))


@frappe.whitelist(allow_guest=True)
def complete_job_card_time(job_card_id, completed_qty, employee=None, time_log_id=None, mobile_token=None):
	try:
		user = _auth(mobile_token)
		quantity = flt(completed_qty)
		if not math.isfinite(quantity) or quantity <= 0:
			raise ScannerAPIError("INVALID_COMPLETED_QTY", "completed_qty must be finite and greater than zero.")

		job_card_id = _document_id(job_card_id)
		frappe.db.sql("select name from `tabJob Card` where name=%s for update", job_card_id)
		doc = _load_job_card(job_card_id, "write")
		employee_row = _employee(employee, user, doc.company)
		matching = [
			row for row in doc.time_logs
			if row.employee == employee_row.name and (not time_log_id or row.name == time_log_id)
		]
		if time_log_id and not matching:
			raise ScannerAPIError("TIME_LOG_NOT_FOUND", f"Time Log '{time_log_id}' was not found for this employee.")
		if matching and matching[-1].to_time:
			row = matching[-1]
			if not math.isclose(flt(row.completed_qty), quantity, abs_tol=1e-9, rel_tol=0):
				raise ScannerAPIError(
					"TIME_LOG_ALREADY_COMPLETED",
					f"Time Log '{row.name}' is already completed with quantity {flt(row.completed_qty):g}.",
				)
			return _context(doc, duplicate_request=True, affected_row=row)

		open_rows = [row for row in matching if not row.to_time]
		if not open_rows:
			if doc.status == "Work In Progress" and doc.actual_start_date and not time_log_id:
				row = doc.append(
					"time_logs",
					{
						"employee": employee_row.name,
						"from_time": doc.actual_start_date,
						"to_time": now_datetime(),
						"completed_qty": quantity,
					},
				)
				doc.save()
				frappe.db.commit()
				return _context(doc, affected_row=row)
			raise ScannerAPIError("NO_OPEN_TIME_LOG", "Start this Job Card in ERPNext before completing it.")
		if len(open_rows) > 1:
			raise ScannerAPIError(
				"MULTIPLE_OPEN_TIME_LOGS",
				"Multiple open time logs exist for this employee. Close or remove the incorrect ERP rows first.",
			)

		row = open_rows[0]
		row.to_time = now_datetime()
		row.completed_qty = quantity
		doc.save()
		frappe.db.commit()
		return _context(doc, affected_row=row)
	except ScannerAPIError as exc:
		frappe.db.rollback()
		return _error(exc.code, str(exc), exc.details, 403 if exc.code == "PERMISSION_DENIED" else 400)
	except frappe.PermissionError:
		frappe.db.rollback()
		return _error("PERMISSION_DENIED", "You do not have permission to update this Job Card.", status=403)
	except Exception as exc:
		frappe.db.rollback()
		return _error("ERP_VALIDATION_FAILED", str(exc))
