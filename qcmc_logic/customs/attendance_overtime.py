import frappe
from frappe.utils import flt


REGULAR_WORKING_HOURS = 8.0
SUPPORTED_SHIFT_TIMES = {
	(6 * 3600, 18 * 3600),
	(18 * 3600, 6 * 3600),
	(7 * 3600, 19 * 3600),
	(19 * 3600, 7 * 3600),
}


def apply_6_to_6_and_7_to_7_overtime(doc, method=None):
	"""Calculate OT after 8 actual hours for supported 12-hour shifts."""
	if doc.status != "Present" or not doc.shift:
		return

	shift = frappe.db.get_value(
		"Shift Type",
		doc.shift,
		["start_time", "end_time", "allow_overtime", "overtime_type"],
		as_dict=True,
	)
	if not shift or not shift.allow_overtime or not _is_supported_shift(shift.start_time, shift.end_time):
		return

	doc.standard_working_hours = REGULAR_WORKING_HOURS
	doc.actual_overtime_duration = calculate_overtime_hours(doc.working_hours)

	if doc.actual_overtime_duration > 0:
		doc.overtime_type = _get_assignment_overtime_type(doc) or shift.overtime_type
	else:
		doc.overtime_type = None


def calculate_overtime_hours(working_hours):
	return round(max(flt(working_hours) - REGULAR_WORKING_HOURS, 0), 2)


def _is_supported_shift(start_time, end_time):
	if start_time is None or end_time is None:
		return False
	return (_seconds(start_time), _seconds(end_time)) in SUPPORTED_SHIFT_TIMES


def _seconds(time_value):
	if hasattr(time_value, "seconds"):
		return time_value.seconds
	parts = [int(part) for part in str(time_value).split(":")]
	return parts[0] * 3600 + parts[1] * 60 + (parts[2] if len(parts) > 2 else 0)


def _get_assignment_overtime_type(doc):
	return frappe.db.get_value(
		"Shift Assignment",
		{
			"employee": doc.employee,
			"shift_type": doc.shift,
			"start_date": ["<=", doc.attendance_date],
			"end_date": [">=", doc.attendance_date],
			"docstatus": 1,
			"status": "Active",
		},
		"overtime_type",
		order_by="start_date desc",
	)
