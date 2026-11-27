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


def _parse_checkpoint_time(value, fieldname):
	if not value:
		raise ScannerAPIError("INVALID_TIME", f"{fieldname} is required.")
	try:
		return frappe.utils.get_datetime(value)
	except (TypeError, ValueError):
		raise ScannerAPIError("INVALID_TIME", f"{fieldname} must be a valid datetime.")


@frappe.whitelist(methods=["POST"])
def save_output_checkpoint(job_card_id, from_time, to_time, completed_qty, checkpoint_id=None):
	"""Append one employee-independent, validated production interval to a draft Job Card."""
	try:
		_auth(None)
		try:
			quantity = float(completed_qty)
		except (TypeError, ValueError):
			raise ScannerAPIError("INVALID_COMPLETED_QTY", "completed_qty must be a finite number greater than zero.")
		if not math.isfinite(quantity) or quantity <= 0:
			raise ScannerAPIError("INVALID_COMPLETED_QTY", "completed_qty must be finite and greater than zero.")
		start = _parse_checkpoint_time(from_time, "from_time")
		end = _parse_checkpoint_time(to_time, "to_time")
		if start >= end:
			raise ScannerAPIError("INVALID_TIME_RANGE", "from_time must be earlier than to_time.")

		job_card_id = _document_id(job_card_id)
		frappe.db.sql("select name from `tabJob Card` where name=%s for update", job_card_id)
		doc = _load_job_card(job_card_id, "write")
		if not doc.work_order or not doc.operation_id:
			raise ScannerAPIError("INVALID_JOB_CARD", "Job Card must be linked to a Work Order operation.")

		# The native child has no idempotency field. The exact interval is the
		# stable checkpoint identity; Job Card row locking serializes retries.
		for row in doc.time_logs:
			if frappe.utils.get_datetime(row.from_time) == start and row.to_time and frappe.utils.get_datetime(row.to_time) == end:
				if math.isclose(flt(row.completed_qty), quantity, abs_tol=1e-9, rel_tol=0):
					return _context(doc, duplicate_request=True, affected_row=row)
				raise ScannerAPIError("CHECKPOINT_CONFLICT", "This interval already exists with a different quantity.")

		for row in doc.time_logs:
			row_start = frappe.utils.get_datetime(row.from_time)
			row_end = frappe.utils.get_datetime(row.to_time) if row.to_time else None
			if row_end is None or (start < row_end and row_start < end):
				raise ScannerAPIError("OVERLAPPING_OUTPUT_INTERVAL", f"Interval overlaps existing Time Log '{row.name or row.idx}'.")

		precision = doc.precision("total_completed_qty")
		if flt(doc.total_completed_qty + quantity, precision) > flt(doc.for_quantity, precision):
			raise ScannerAPIError("OVERPRODUCTION", "Checkpoint quantity exceeds the remaining Job Card quantity.")

		row = doc.append("time_logs", {
			"from_time": start,
			"to_time": end,
			"completed_qty": quantity,
		})
		doc.status = "Work In Progress"
		doc.save()
		return _context(doc, affected_row=row)
	except ScannerAPIError as exc:
		return _error(exc.code, str(exc), exc.details, 403 if exc.code == "PERMISSION_DENIED" else 400)
	except frappe.PermissionError:
		return _error("PERMISSION_DENIED", "You do not have permission to update this Job Card.", status=403)
	except Exception as exc:
		return _error("ERP_VALIDATION_FAILED", str(exc))


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


def _process_card_and_job(process_card_id, job_card_id):
	"""Resolve explicit Process Card membership before touching native Time Logs."""
	from qcmc_logic.api.process_card_workbench import _job_card, _lock_process_card

	card = _lock_process_card(process_card_id)
	if card.status not in {"Draft", "In Progress"}:
		frappe.throw("Production output can only be entered on a Draft or In Progress Process Card.")
	if job_card_id not in {row.job_card for row in card.jobs}:
		frappe.throw("The selected Job Card is not linked to this Process Card.")
	_job_card(job_card_id, card.company, card.workstation)
	return card


def _decimal_checkpoint_qty(value, fieldname, precision):
	from decimal import Decimal, InvalidOperation

	try:
		if value is None or isinstance(value, bool):
			raise InvalidOperation
		quantity = Decimal(str(value).strip())
	except (InvalidOperation, TypeError, ValueError):
		frappe.throw(f"{fieldname} must be a finite nonnegative number.")
	if not quantity.is_finite() or quantity < 0:
		frappe.throw(f"{fieldname} must be a finite nonnegative number.")
	precision = int(precision or 0)
	try:
		rounded_decimal = quantity.quantize(Decimal(1).scaleb(-precision))
	except InvalidOperation:
		frappe.throw(f"{fieldname} is outside the supported numeric range.")
	if quantity != rounded_decimal:
		frappe.throw(f"{fieldname} exceeds the Job Card quantity precision of {precision} decimals.")
	return float(rounded_decimal)


def _operational_output_row(row):
	return {
		"time_log_id": row.name,
		"from_time": str(row.from_time or ""),
		"to_time": str(row.to_time or ""),
		"good_qty": float(row.get("qcmc_good_qty") or 0),
		"rejected_qty": float(row.get("qcmc_rejected_qty") or 0),
		"remarks": row.get("qcmc_output_remarks") or "",
		"entered_at": str(row.get("qcmc_output_entered_at") or ""),
		"entered_by": row.get("qcmc_output_entered_by") or "",
		"revision": int(row.get("qcmc_output_revision") or 0),
		"correction_history": frappe.parse_json(row.get("qcmc_output_correction_history") or "[]"),
	}


def _checkpoint_output_rows(job_card, process_card):
	return [
		_operational_output_row(row)
		for row in (job_card.get("time_logs") or [])
		if row.get("qcmc_process_card") == process_card
		and int(row.get("qcmc_output_revision") or 0) > 0
	]


def _validate_output_interval(card, from_time, to_time):
	start = _parse_checkpoint_time(from_time, "from_time")
	end = _parse_checkpoint_time(to_time, "to_time")
	shift_start = frappe.utils.get_datetime(card.shift_start)
	shift_end = frappe.utils.get_datetime(card.shift_end)
	if start >= end or start < shift_start or end > shift_end:
		frappe.throw("Checkpoint interval must be positive and fall within the Process Card shift.")
	return start, end


def _job_card_operation_output(job, include_rejected=True):
	output_rows = [
		log for log in (job.time_logs or [])
		if int(log.get("qcmc_output_revision") or 0) > 0
	]
	operational_good = sum(flt(log.get("qcmc_good_qty")) for log in output_rows)
	operational_rejected = sum(flt(log.get("qcmc_rejected_qty")) for log in output_rows)
	return (
		flt(job.total_completed_qty) + operational_good,
		flt(job.total_completed_qty) + operational_good + (operational_rejected if include_rejected else 0),
	)


def _validate_operation_output_limits(job):
	"""Limit each operation to its Work Order quantity and upstream accepted output."""
	if not job.work_order or not job.operation_id:
		frappe.throw("Job Card must reference a Work Order operation.")
	if job.get("is_corrective_job_card"):
		frappe.throw("Operational production output cannot be recorded on a corrective Job Card.")

	frappe.db.sql("select name from `tabWork Order` where name=%s for update", job.work_order)
	work_order = frappe.get_doc("Work Order", job.work_order)
	work_order.check_permission("read")
	if work_order.docstatus != 1 or work_order.status in {"Stopped", "Completed", "Cancelled"}:
		frappe.throw("Production output cannot be recorded on a closed Work Order.")
	operations = sorted(
		work_order.operations,
		key=lambda operation: (flt(operation.sequence_id), int(operation.idx or 0)),
	)
	operation_index = next(
		(index for index, operation in enumerate(operations) if operation.name == job.operation_id),
		None,
	)
	if operation_index is None:
		frappe.throw("Job Card operation is not part of its Work Order.")

	def operation_totals(operation_id):
		filters = {
			"work_order": work_order.name,
			"operation_id": operation_id,
			"docstatus": ["<", 2],
			"is_corrective_job_card": 0,
		}
		rows = frappe.get_list(
			"Job Card",
			filters=filters,
			fields=["name"],
			limit_page_length=0,
		)
		visible_names = {row.name for row in rows}
		if job.operation_id == operation_id:
			visible_names.add(job.name)
		if frappe.db.count("Job Card", filters) != len(visible_names):
			frappe.throw("You must have read access to every Job Card on this Work Order operation.", frappe.PermissionError)

		total_output = 0
		good_output = 0
		for name in visible_names:
			operation_job = job if name == job.name else frappe.get_doc("Job Card", name)
			if operation_job is not job:
				operation_job.check_permission("read")
			good, total = _job_card_operation_output(operation_job)
			good_output += good
			total_output += total
		return good_output, total_output

	precision = job.precision("for_quantity")
	work_order_quantity = flt(work_order.qty, precision)
	current_good, current_total = operation_totals(job.operation_id)
	if current_total > work_order_quantity:
		frappe.throw("Recorded output exceeds the Work Order quantity.")

	if operation_index:
		previous_good, _previous_total = operation_totals(operations[operation_index - 1].name)
		if flt(current_total, precision) > flt(previous_good, precision):
			frappe.throw(
				"Operation output exceeds the accepted quantity from the previous Work Order operation."
			)

	if operation_index + 1 < len(operations):
		_next_good, next_total = operation_totals(operations[operation_index + 1].name)
		if flt(next_total, precision) > flt(current_good, precision):
			frappe.throw("Output correction would leave the next Work Order operation above the accepted quantity.")


def _save_operational_output(
	card, job, start, end, good_qty, rejected_qty, remarks=None, row=None,
	enforce_operation_limits=False,
):
	precision = job.precision("for_quantity")
	good = _decimal_checkpoint_qty(good_qty, "Good quantity", precision)
	rejected = _decimal_checkpoint_qty(rejected_qty, "Rejected quantity", precision)
	if not row:
		for existing in job.time_logs:
			is_output_row = int(existing.get("qcmc_output_revision") or 0) > 0
			is_official_output = flt(existing.get("completed_qty")) > 0
			if not is_output_row and not is_official_output:
				continue
			if frappe.utils.get_datetime(existing.from_time) == start and existing.to_time and frappe.utils.get_datetime(existing.to_time) == end:
				if existing.get("qcmc_process_card") != card.name:
					frappe.throw("This checkpoint interval is already recorded on this Job Card.")
				if (flt(existing.get("qcmc_good_qty")) == good and flt(existing.get("qcmc_rejected_qty")) == rejected and (existing.get("qcmc_output_remarks") or "") == (remarks or "")):
					return _operational_output_row(existing), True
				frappe.throw("This checkpoint already has an entry. Use Correct Entry to revise it.")
			if not existing.to_time or (start < frappe.utils.get_datetime(existing.to_time) and frappe.utils.get_datetime(existing.from_time) < end):
				frappe.throw("Checkpoint interval overlaps an existing Job Card Time Log.")
	other_operational_qty = sum(
		flt(existing.get("qcmc_good_qty")) + flt(existing.get("qcmc_rejected_qty"))
		for existing in job.time_logs
		if existing is not row
		and existing.get("qcmc_process_card")
		and int(existing.get("qcmc_output_revision") or 0) > 0
	)
	if flt(job.total_completed_qty + other_operational_qty + good + rejected, precision) > flt(job.for_quantity, precision):
		frappe.throw("Output would exceed the Job Card quantity after including official and previously recorded operational output.")
	if not row:
		# ERPNext derives official totals from completed_qty. Refuse to save if existing rows are already inconsistent.
		if job.sub_operations:
			frappe.throw("Operational checkpoints cannot be added to a Job Card with sub-operations.")
		native_total = sum(flt(log.completed_qty) for log in job.time_logs)
		if flt(native_total, precision) != flt(job.total_completed_qty, precision):
			frappe.throw("Job Card Time Logs do not match its official completed quantity. Reconcile the Job Card before entering operational output.")
		row = job.append("time_logs", {
			"from_time": start, "to_time": end, "completed_qty": 0,
			"qcmc_process_card": card.name,
			"qcmc_good_qty": good,
			"qcmc_rejected_qty": rejected,
			"qcmc_output_remarks": remarks or "",
			"qcmc_output_entered_at": now_datetime(),
			"qcmc_output_entered_by": frappe.session.user,
			"qcmc_output_revision": 1,
			"qcmc_output_correction_history": "[]",
		})
	else:
		row.qcmc_good_qty = good
		row.qcmc_rejected_qty = rejected
		row.qcmc_output_remarks = remarks or ""
		row.qcmc_output_revision = int(row.get("qcmc_output_revision") or 0) + 1
		row.qcmc_output_entered_at = now_datetime()
		row.qcmc_output_entered_by = frappe.session.user
	if enforce_operation_limits:
		_validate_operation_output_limits(job)
	job.flags.qcmc_operational_checkpoint_update = True
	job.save()
	return _operational_output_row(row), False


@frappe.whitelist(methods=["POST"])
def save_process_card_output(process_card, job_card, from_time, to_time, good_qty, rejected_qty=0, remarks=None):
	"""Record operational checkpoint output on an explicitly linked Job Card.

	Native completed_qty remains zero; Task 01's official ERPNext posting path is untouched.
	"""
	card = _process_card_and_job(process_card, job_card)
	start, end = _validate_output_interval(card, from_time, to_time)
	job_card = _document_id(job_card)
	frappe.db.sql("select name from `tabJob Card` where name=%s for update", job_card)
	job = _load_job_card(job_card, "write")
	if job.company != card.company or job.workstation != card.workstation:
		frappe.throw("Job Card Company and Workstation must match the Process Card.")
	row, duplicate = _save_operational_output(
		card, job, start, end, good_qty, rejected_qty, remarks,
		enforce_operation_limits=True,
	)
	return {"entry": row, "duplicate_request": duplicate, "official_completed_qty": flt(job.total_completed_qty)}


@frappe.whitelist(methods=["POST"])
def save_process_card_output_batch(rows):
	"""Save independent output rows using the same validation and storage path as mobile entry."""
	try:
		rows = frappe.parse_json(rows) if isinstance(rows, str) else rows
	except (TypeError, ValueError):
		frappe.throw("Batch rows must be a valid list.")
	if not isinstance(rows, list) or len(rows) > 500:
		frappe.throw("Submit between one and 500 output rows.")
	results = []
	for index, values in enumerate(rows):
		if not isinstance(values, dict):
			results.append({"index": index, "success": False, "message": "Invalid row."})
			continue
		savepoint = f"qcmc_output_row_{index}"
		frappe.db.savepoint(savepoint)
		try:
			result = save_process_card_output(
				values.get("process_card"), values.get("job_card"), values.get("from_time"),
				values.get("to_time"), values.get("good_qty"), values.get("rejected_qty", 0),
				values.get("remarks"),
			)
			results.append({"index": index, "success": True, **result})
		except Exception as exc:
			frappe.db.rollback(save_point=savepoint)
			results.append({"index": index, "success": False, "message": str(exc)})
	return {"results": results, "success_count": sum(row["success"] for row in results)}


@frappe.whitelist(methods=["POST"])
def correct_process_card_output(process_card, job_card, time_log_id, expected_revision, good_qty, rejected_qty=0, remarks=None, reason=None):
	"""Correct an operational checkpoint, recording the complete previous-value audit."""
	import json

	from qcmc_logic.api.process_card_workbench import _job_card, _lock_process_card

	card = _lock_process_card(process_card)
	if card.status not in {"Draft", "In Progress"}:
		frappe.throw("Production output cannot be corrected on a locked Process Card.")
	if job_card not in {row.job_card for row in card.jobs}:
		frappe.throw("The selected Job Card is not linked to this Process Card.")
	if not reason or not str(reason).strip():
		frappe.throw("Enter a correction reason.")
	_job_card(job_card, card.company, card.workstation)
	frappe.db.sql("select name from `tabJob Card` where name=%s for update", job_card)
	job = _load_job_card(job_card, "write")
	row = next((row for row in job.time_logs if row.name == time_log_id and row.get("qcmc_process_card") == card.name), None)
	if not row or int(row.get("qcmc_output_revision") or 0) <= 0:
		frappe.throw("Operational checkpoint entry not found for this Process Card.")
	if int(row.get("qcmc_output_revision") or 0) != int(expected_revision):
		frappe.throw("This checkpoint changed after you loaded it. Refresh before correcting it.", frappe.TimestampMismatchError)
	precision = job.precision("for_quantity")
	good = _decimal_checkpoint_qty(good_qty, "Good quantity", precision)
	rejected = _decimal_checkpoint_qty(rejected_qty, "Rejected quantity", precision)
	start, end = frappe.utils.get_datetime(row.from_time), frappe.utils.get_datetime(row.to_time)
	before = _operational_output_row(row)
	history = before["correction_history"]
	history.append({
		"previous_good_qty": before["good_qty"], "previous_rejected_qty": before["rejected_qty"],
		"previous_remarks": before["remarks"], "revised_good_qty": good,
		"revised_rejected_qty": rejected, "revised_remarks": remarks or "",
		"reason": str(reason).strip(), "user": frappe.session.user, "timestamp": str(now_datetime()),
	})
	row.qcmc_output_correction_history = json.dumps(history, separators=(",", ":"))
	updated, duplicate = _save_operational_output(
		card, job, start, end, good, rejected, remarks,
		row=row, enforce_operation_limits=True,
	)
	return {"entry": updated, "duplicate_request": duplicate, "official_completed_qty": flt(job.total_completed_qty)}


@frappe.whitelist(methods=["GET"])
def get_process_card_output_entries(job_card_id):
	"""List permission-checked operational intervals for the standard Job Card form."""
	from qcmc_logic.api.process_card_workbench import _process_card

	job = _load_job_card(job_card_id, "read")
	result = []
	for row in job.time_logs:
		if not row.get("qcmc_process_card") or int(row.get("qcmc_output_revision") or 0) <= 0:
			continue
		card = _process_card(row.qcmc_process_card)
		if job.name not in {link.job_card for link in card.jobs}:
			frappe.throw("Operational output is linked to a Process Card that does not contain this Job Card.")
		result.append({"process_card": card.name, **_operational_output_row(row)})
	return result
