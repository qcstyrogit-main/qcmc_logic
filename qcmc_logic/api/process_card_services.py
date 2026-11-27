import frappe
from frappe import _
from frappe.utils import get_datetime, time_diff_in_seconds


@frappe.whitelist(methods=["POST"])
def save_process_card_participation(
	process_card,
	job_card,
	employee,
	from_time=None,
	to_time=None,
	pay_mode=None,
	mca_approval_reference=None,
	time_log_id=None,
):
	"""Create or update an employee participation interval on a native Job Card Time Log."""
	from qcmc_logic.api.process_card_workbench import _job_card, _lock_process_card

	card = _lock_process_card(process_card)
	job, _work_order = _job_card(job_card, card.company, card.workstation)
	job.check_permission("write")
	if job.name not in {row.job_card for row in card.jobs}:
		frappe.throw(_("Job Card is not linked to this Process Card."))

	if time_log_id:
		row = next(
			(
				entry for entry in job.time_logs
				if entry.name == time_log_id and entry.get("qcmc_process_card") == card.name
				and entry.get("employee") == employee
				and not int(entry.get("qcmc_output_revision") or 0)
			),
			None,
		)
		if not row:
			frappe.throw(_("Employee participation row was not found on this Job Card."))
		if from_time is not None:
			row.from_time = from_time
		if to_time is not None:
			row.to_time = to_time
		if pay_mode is not None:
			row.qcmc_pay_mode = pay_mode
		if mca_approval_reference is not None:
			row.qcmc_mca_approval_reference = mca_approval_reference.strip()
	else:
		if not from_time:
			frappe.throw(_("From Time is required for a new participation row."))
		row = job.append("time_logs", {
			"employee": employee,
			"from_time": from_time,
			"to_time": to_time,
			"completed_qty": 0,
			"qcmc_process_card": card.name,
			"qcmc_pay_mode": pay_mode,
			"qcmc_mca_approval_reference": (mca_approval_reference or "").strip(),
		})
		job.status = "Work In Progress"

	job.save()
	return {
		"process_card": card.name,
		"job_card": job.name,
		"time_log_id": row.name,
		"employee": row.employee,
		"from_time": str(row.from_time or ""),
		"to_time": str(row.to_time or ""),
		"pay_mode": row.qcmc_pay_mode,
		"mca_approval_reference": row.qcmc_mca_approval_reference or "",
	}


def _clipped_intervals(intervals, start, end):
	clipped = []
	for left, right in intervals:
		left, right = max(get_datetime(left), start), min(get_datetime(right), end)
		if left < right:
			clipped.append((left, right))
	return sorted(clipped)


def _union_seconds(intervals):
	if not intervals:
		return 0
	intervals = sorted(intervals)
	total = 0
	start, end = intervals[0]
	for next_start, next_end in intervals[1:]:
		if next_start <= end:
			end = max(end, next_end)
		else:
			total += time_diff_in_seconds(end, start)
			start, end = next_start, next_end
	total += time_diff_in_seconds(end, start)
	return total


def _subtract_intervals(source, excluded):
	result = []
	for start, end in source:
		remaining = [(start, end)]
		for excluded_start, excluded_end in excluded:
			next_remaining = []
			for left, right in remaining:
				if excluded_end <= left or excluded_start >= right:
					next_remaining.append((left, right))
				else:
					if left < excluded_start:
						next_remaining.append((left, excluded_start))
					if excluded_end < right:
						next_remaining.append((excluded_end, right))
			remaining = next_remaining
		result.extend(remaining)
	return _clipped_intervals(result, source[0][0], source[-1][1]) if source else []


@frappe.whitelist(methods=["GET"])
def get_process_card_shift_summary(process_card):
	"""Return a permission-checked shift summary using linked production and transaction events."""
	from qcmc_logic.api.process_card_workbench import (
		_job_card,
		_process_card,
		_production_output_summary,
	)

	card = _process_card(process_card)
	section_access = {doctype: bool(frappe.has_permission(doctype, "read"))
		for doctype in ("Downtime Entry", "Quality Inspection", "Asset Repair", "Employee")}

	start, end = get_datetime(card.shift_start), get_datetime(card.shift_end)
	shift_seconds = time_diff_in_seconds(end, start)
	job_docs = [
		_job_card(row.job_card, card.company, card.workstation, allow_historical=True)[0]
		for row in card.jobs
	]
	production = _production_output_summary(card, job_docs)
	manpower_participation = []
	employees = {}
	for job in (job_docs if section_access["Employee"] else []):
		for row in job.get("time_logs") or []:
			if (
				row.get("qcmc_process_card") != card.name
				or not row.get("employee")
				or int(row.get("qcmc_output_revision") or 0) > 0
			):
				continue
			if row.employee not in employees:
				employee = frappe.get_doc("Employee", row.employee)
				employee.check_permission("read")
				employees[row.employee] = employee
			manpower_participation.append({
				"job_card": job.name,
				"work_order": job.work_order,
				"employee": row.employee,
				"employee_name": employees[row.employee].employee_name,
				"from_time": str(row.from_time or ""),
				"to_time": str(row.to_time or ""),
				"pay_mode": row.get("qcmc_pay_mode"),
				"mca_approval_reference": row.get("qcmc_mca_approval_reference") or "",
			})
	output_intervals = []
	output_sources = []
	for job in production["per_job"]:
		for entry in job["entries"]:
			if entry["good_qty"] + entry["rejected_qty"] > 0:
				output_intervals.append((entry["from_time"], entry["to_time"]))
				output_sources.append({
					"job_card": job["job_card"],
					"time_log_id": entry["time_log_id"],
					"from_time": entry["from_time"],
					"to_time": entry["to_time"],
				})

	downtime_rows = frappe.get_list(
		"Downtime Entry",
		filters={
			"workstation": card.workstation,
			"from_time": ["<", end],
			"to_time": [">", start],
		},
		fields=["name", "qcmc_process_card", "qcmc_job_card", "from_time", "to_time", "stop_reason", "remarks"],
		limit_page_length=0,
	) if section_access["Downtime Entry"] else []
	downtime_intervals = []
	downtime_entries = []
	for row in downtime_rows:
		entry = frappe.get_doc("Downtime Entry", row.name)
		entry.check_permission("read")
		downtime_intervals.append((entry.from_time, entry.to_time))
		downtime_entries.append({
			"name": entry.name,
			"process_card": entry.get("qcmc_process_card"),
			"job_card": entry.qcmc_job_card,
			"from_time": str(entry.from_time),
			"to_time": str(entry.to_time),
			"stop_reason": entry.stop_reason,
			"remarks": entry.remarks,
		})

	quality_rows = frappe.get_list(
		"Quality Inspection",
		filters={"qcmc_process_card": card.name, "docstatus": ["!=", 2]},
		fields=["name", "reference_name", "qcmc_output_time_log", "status", "inspected_by"],
		limit_page_length=0,
	) if section_access["Quality Inspection"] else []
	quality_inspections = []
	qa_rejections = []
	measurements = []
	for row in quality_rows:
		inspection = frappe.get_doc("Quality Inspection", row.name)
		inspection.check_permission("read")
		inspection_rejected_qty = 0
		for reading in inspection.readings:
			rejected_qty = float(reading.get("qcmc_rejected_qty") or 0)
			inspection_rejected_qty += rejected_qty
			if rejected_qty:
				qa_rejections.append({
					"quality_inspection": inspection.name,
					"job_card": inspection.reference_name,
					"specification": reading.specification,
					"reject_reason": reading.get("qcmc_reject_reason"),
					"rejected_qty": rejected_qty,
				})
			reading_values = [reading.get(f"reading_{i}") for i in range(1, 11)]
			if reading.get("qcmc_measurement_uom") or reading.get("reading_value") or any(reading_values):
				measurements.append({
					"quality_inspection": inspection.name,
					"job_card": inspection.reference_name,
					"specification": reading.specification,
					"reading_value": reading.get("reading_value"),
					"readings": reading_values,
					"uom": reading.get("qcmc_measurement_uom"),
					"result": reading.status,
				})
		quality_inspections.append({
			"name": inspection.name,
			"job_card": inspection.reference_name,
			"output_time_log": inspection.get("qcmc_output_time_log"),
			"qa_start": str(inspection.get("qcmc_qa_start") or ""),
			"qa_end": str(inspection.get("qcmc_qa_end") or ""),
			"work_order": inspection.get("qcmc_work_order"),
			"status": inspection.status,
			"inspected_by": inspection.inspected_by,
			"qa_rejected_qty": inspection_rejected_qty,
		})

	repair_rows = frappe.get_list(
		"Asset Repair",
		filters={"qcmc_process_card": card.name, "docstatus": ["!=", 2]},
		fields=[
			"name", "asset", "qcmc_workstation", "qcmc_job_card", "failure_date",
			"completion_date", "repair_status", "custom_bd_class",
			"custom_nature_of_breakdown", "custom_action_taken",
		],
		limit_page_length=0,
	) if section_access["Asset Repair"] else []
	breakdowns = []
	for row in repair_rows:
		repair = frappe.get_doc("Asset Repair", row.name)
		repair.check_permission("read")
		breakdowns.append({
			"name": repair.name,
			"asset": repair.asset,
			"workstation": repair.get("qcmc_workstation"),
			"job_card": repair.get("qcmc_job_card"),
			"failure_date": str(repair.failure_date or ""),
			"completion_date": str(repair.completion_date or ""),
			"repair_status": repair.repair_status,
			"breakdown_class": repair.get("custom_bd_class"),
			"nature_of_breakdown": repair.get("custom_nature_of_breakdown"),
			"actions_taken": repair.get("custom_action_taken"),
		})

	clipped_downtime = _clipped_intervals(downtime_intervals, start, end)
	clipped_output = _clipped_intervals(output_intervals, start, end)
	downtime_seconds = _union_seconds(clipped_downtime)
	available_seconds = max(shift_seconds - downtime_seconds, 0)
	run_seconds = _union_seconds(_subtract_intervals(clipped_output, clipped_downtime))
	return {
		"process_card": card.name,
		"workstation": card.workstation,
		"company": card.company,
		"shift_type": card.shift_type,
		"shift_start": str(card.shift_start),
		"shift_end": str(card.shift_end),
		"production_output": production,
		"manpower_participation": manpower_participation,
		"section_access": section_access,
		"machine_metrics": {
			"shift_hours": round(shift_seconds / 3600, 4),
			"downtime_hours": round(downtime_seconds / 3600, 4) if section_access["Downtime Entry"] else None,
			"available_hours": round(available_seconds / 3600, 4) if section_access["Downtime Entry"] else None,
			"availability_percent": (round(available_seconds / shift_seconds * 100, 2) if shift_seconds > 0 else 0) if section_access["Downtime Entry"] else None,
			"actual_run_hours": None,
			"recorded_output_interval_hours": round(run_seconds / 3600, 4) if section_access["Downtime Entry"] else None,
			"definitions": {
				"availability": "Process Card shift duration minus the union of linked Downtime Entry intervals clipped to the shift.",
				"actual_run_hours": "Recorded production interval hours: union of positive-output intervals clipped to the shift, less downtime overlap. This is not measured machine runtime.",
				"breakdown_duration": "Asset Repair failure-to-completion duration is not counted as machine downtime.",
			},
			"availability_source_events": [row["name"] for row in downtime_entries],
			"actual_run_source_events": output_sources,
		},
		"quality_inspections": quality_inspections,
		"qa_rejections": qa_rejections,
		"measurements": measurements,
		"downtime_entries": downtime_entries,
		"breakdowns": breakdowns,
	}
