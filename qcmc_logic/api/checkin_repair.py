from __future__ import annotations

from datetime import datetime, timedelta

import frappe
from frappe.utils import get_datetime, getdate

from hrms.hr.doctype.shift_assignment.shift_assignment import (
	get_actual_start_end_datetime_of_shift,
	get_shift_details,
)


CHECKIN_REPAIR_ROLES = {"System Manager", "HR Manager", "Payroll Manager"}


def _require_checkin_repair_role():
	if frappe.session.user == "Administrator":
		return

	if CHECKIN_REPAIR_ROLES.intersection(set(frappe.get_roles())):
		return

	frappe.throw(
		"Only System Manager, HR Manager, or Payroll Manager can repair employee checkins.",
		frappe.PermissionError,
	)


def _range_end(to_date):
	return datetime.combine(getdate(to_date), datetime.max.time()).replace(microsecond=0)


def _assignment_for_date(employee, attendance_date):
	assignments = frappe.get_all(
		"Shift Assignment",
		filters={
			"employee": employee,
			"docstatus": 1,
			"start_date": ["<=", attendance_date],
		},
		or_filters=[["end_date", ">=", attendance_date], ["end_date", "is", "not set"]],
		fields=["name", "shift_type", "status", "overtime_type", "modified"],
		order_by="status asc, modified desc",
	)
	active = [row for row in assignments if row.status == "Active"]
	return (active or assignments or [None])[0]


def _shift_details_from_assignments(employee, checkin_time):
	assignment = _assignment_for_date(employee, getdate(checkin_time))
	if not assignment:
		return None

	details = get_shift_details(assignment.shift_type, get_datetime(checkin_time))
	if not details:
		return None

	details.overtime_type = assignment.overtime_type or None
	return details


def _get_shift_details(employee, checkin_time):
	details = get_actual_start_end_datetime_of_shift(employee, get_datetime(checkin_time), True)
	if details:
		return details
	return _shift_details_from_assignments(employee, checkin_time)


def _link_existing_attendance(checkin):
	attendance_date = getdate(checkin.shift_start or checkin.time)
	attendance = frappe.db.exists(
		"Attendance",
		{
			"employee": checkin.employee,
			"attendance_date": attendance_date,
			"docstatus": ["<", 2],
		},
	)
	if attendance:
		frappe.db.set_value("Employee Checkin", checkin.name, "attendance", attendance, update_modified=False)
		return attendance
	return None


def _sync_shifts(shifts, to_date):
	last_sync = _range_end(getdate(to_date) + timedelta(days=1))
	for shift in sorted(shifts):
		frappe.db.set_value(
			"Shift Type",
			shift,
			"last_sync_of_checkin",
			last_sync,
			update_modified=False,
		)
	return last_sync


@frappe.whitelist()
def repair_employee_checkins(employee, from_date, to_date, run_auto_attendance=1):
	"""Repair checkin shift metadata and attendance links for one employee/date range."""
	_require_checkin_repair_role()

	checkins = frappe.get_all(
		"Employee Checkin",
		filters={
			"employee": employee,
			"time": ["between", [get_datetime(from_date), _range_end(to_date)]],
		},
		fields=[
			"name",
			"employee",
			"time",
			"shift",
			"shift_start",
			"shift_end",
			"shift_actual_start",
			"shift_actual_end",
			"offshift",
			"attendance",
		],
		order_by="time",
	)

	updated_shift = 0
	linked_existing = 0
	unresolved = []
	affected_shifts = set()

	for checkin in checkins:
		needs_shift = not checkin.shift or checkin.offshift or not checkin.shift_start or not checkin.shift_end
		if needs_shift:
			details = _get_shift_details(employee, checkin.time)
			if not details:
				unresolved.append(checkin.name)
				continue

			frappe.db.set_value(
				"Employee Checkin",
				checkin.name,
				{
					"shift": details.shift_type.name,
					"shift_start": details.start_datetime,
					"shift_end": details.end_datetime,
					"shift_actual_start": details.actual_start,
					"shift_actual_end": details.actual_end,
					"offshift": 0,
					"overtime_type": details.overtime_type or None,
				},
				update_modified=False,
			)
			updated_shift += 1
			checkin.shift = details.shift_type.name
			checkin.shift_start = details.start_datetime
			checkin.shift_end = details.end_datetime
			checkin.shift_actual_start = details.actual_start
			checkin.shift_actual_end = details.actual_end
			checkin.offshift = 0

		if checkin.shift:
			affected_shifts.add(checkin.shift)

		if not checkin.attendance and _link_existing_attendance(checkin):
			linked_existing += 1

	frappe.db.commit()

	last_sync = _sync_shifts(affected_shifts, to_date) if affected_shifts else None
	frappe.db.commit()

	results = []
	if int(run_auto_attendance or 0):
		for shift in sorted(affected_shifts):
			result = frappe.get_doc("Shift Type", shift).process_auto_attendance(is_manually_triggered=True)
			results.append({"shift": shift, "result": result})

	remaining_unlinked = frappe.db.count(
		"Employee Checkin",
		{
			"employee": employee,
			"time": ["between", [get_datetime(from_date), _range_end(to_date)]],
			"attendance": ["is", "not set"],
		},
	)
	attendance_count = frappe.db.count(
		"Attendance",
		{
			"employee": employee,
			"attendance_date": ["between", [getdate(from_date), getdate(to_date)]],
			"docstatus": ["<", 2],
		},
	)

	return {
		"checkins": len(checkins),
		"updated_shift": updated_shift,
		"linked_existing_attendance": linked_existing,
		"unresolved_checkins": unresolved,
		"affected_shifts": sorted(affected_shifts),
		"last_sync_of_checkin": last_sync,
		"auto_attendance": results,
		"remaining_unlinked_checkins": remaining_unlinked,
		"attendance_count": attendance_count,
	}
