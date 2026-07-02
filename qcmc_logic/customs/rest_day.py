import frappe
from frappe.utils import getdate


DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
REST_DAY_TOKENS = {
	"MON": "Monday",
	"MONDAY": "Monday",
	"TUE": "Tuesday",
	"TUESDAY": "Tuesday",
	"WED": "Wednesday",
	"WEDNESDAY": "Wednesday",
	"THU": "Thursday",
	"THUR": "Thursday",
	"THURSDAY": "Thursday",
	"FRI": "Friday",
	"FRIDAY": "Friday",
	"SAT": "Saturday",
	"SATURDAY": "Saturday",
	"SUN": "Sunday",
	"SUNDAY": "Sunday",
}


def get_rest_days_for_shift(shift_name):
	if not shift_name:
		return {"Saturday", "Sunday"}

	normalized = (
		shift_name.upper()
		.replace("(", " ")
		.replace(")", " ")
		.replace("-", " ")
		.replace("/", " ")
	)
	parts = normalized.split()
	rest_days = set()
	for index, part in enumerate(parts):
		if part != "RD":
			continue
		for neighbor in (index - 1, index + 1):
			if neighbor < 0 or neighbor >= len(parts):
				continue
			day = REST_DAY_TOKENS.get(parts[neighbor])
			if day:
				rest_days.add(day)

	if rest_days:
		rest_days.add("Sunday")
		return rest_days

	return {"Saturday", "Sunday"}


def is_rest_day(attendance_date, shift_name=None):
	day_name = DAYS[getdate(attendance_date).weekday()]
	return day_name in get_rest_days_for_shift(shift_name)


def is_rest_day_from_work_days(attendance_date, work_days=None, shift_name=None):
	day_name = DAYS[getdate(attendance_date).weekday()]
	if work_days:
		return day_name not in set(work_days)
	return day_name in {"Saturday", "Sunday"}


def get_employee_roster_work_days(employee, start_date, end_date):
	shift_schedule_assignments = frappe.get_all(
		"Shift Assignment",
		filters=[
			["employee", "=", employee],
			["docstatus", "=", 1],
			["start_date", "<=", end_date],
			["shift_schedule_assignment", "is", "set"],
		],
		or_filters=[
			["end_date", ">=", start_date],
			["end_date", "is", "not set"],
		],
		pluck="shift_schedule_assignment",
	)
	if not shift_schedule_assignments:
		return None

	shift_schedules = frappe.get_all(
		"Shift Schedule Assignment",
		filters={"name": ["in", list(set(shift_schedule_assignments))]},
		pluck="shift_schedule",
	)
	if not shift_schedules:
		return None

	work_days = frappe.get_all(
		"Assignment Rule Day",
		filters={"parent": ["in", list(set(shift_schedules))]},
		pluck="day",
	)
	return set(work_days) or None
