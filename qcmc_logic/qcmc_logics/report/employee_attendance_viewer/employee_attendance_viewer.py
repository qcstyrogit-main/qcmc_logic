import frappe
from frappe import _

from qcmc_logic.api.employee_attendance_schedule import (
	get_employee_directory,
	get_employee_schedule,
	get_payroll_period_dates,
)


def execute(filters=None):
	filters = frappe._dict(filters or {})
	frequency = filters.get("payroll_frequency") or "Bimonthly"
	payroll_period_mode = filters.get("payroll_period_mode")
	company = filters.get("company")
	payroll_period = filters.get("payroll_period")
	employee = _parse_employee_filter(filters.get("employee"))

	if not company or not payroll_period:
		return _get_employee_columns(), [], _("Select Company and Payroll Period."), None, []

	period = get_payroll_period_dates(payroll_period, frequency, payroll_period_mode)
	if employee:
		try:
			return _get_schedule_result(
				employee, company, period["payroll_period"], frequency, payroll_period_mode
			)
		except frappe.ValidationError:
			return _get_employee_list_result(
				company, period["payroll_period"], frequency, payroll_period_mode
			)

	return _get_employee_list_result(company, period["payroll_period"], frequency, payroll_period_mode)


def _get_employee_list_result(company, payroll_period, frequency, payroll_period_mode=None):
	result = get_employee_directory(
		company=company,
		payroll_period=payroll_period,
		payroll_frequency=frequency,
		payroll_period_mode=payroll_period_mode,
	)
	rows = []
	for employee in result.get("employees", []):
		rows.append(
			{
				"employee": employee.get("employee"),
				"employee_name": employee.get("employee_name"),
				"department": employee.get("department"),
				"branch": employee.get("branch"),
				"shift": employee.get("default_shift") or employee.get("shift"),
				"status": employee.get("status"),
				"payroll_type": employee.get("custom_payroll_type"),
			}
		)

	message = _(
		"Showing {0} employee(s). Click an employee row to view the attendance schedule."
	).format(len(rows))
	report_summary = [
		{
			"value": len(rows),
			"indicator": "Blue",
			"label": _("Employees"),
			"datatype": "Int",
		},
		{
			"value": result.get("scheduled_employees") or 0,
			"indicator": "Green",
			"label": _("With Shift"),
			"datatype": "Int",
		},
	]
	return _get_employee_columns(), rows, message, None, report_summary


def _parse_employee_filter(employee):
	if not employee:
		return ""
	return str(employee).split(" - ", 1)[0].strip()


def _get_schedule_result(employee, company, payroll_period, frequency, payroll_period_mode=None):
	result = get_employee_schedule(
		employee=employee,
		company=company,
		payroll_period=payroll_period,
		payroll_frequency=frequency,
		payroll_period_mode=payroll_period_mode,
	)
	rows = result.get("rows", [])
	report_summary = _get_schedule_summary(rows)
	message = _("Attendance schedule for {0}").format(
		result.get("employee_name") or employee
	)
	return _get_schedule_columns(), rows, message, None, report_summary


def _get_employee_columns():
	return [
		{
			"label": _("Employee ID"),
			"fieldname": "employee",
			"fieldtype": "Link",
			"options": "Employee",
			"width": 160,
		},
		{
			"label": _("Employee Name"),
			"fieldname": "employee_name",
			"fieldtype": "Data",
			"width": 260,
		},
		{"label": _("Department"), "fieldname": "department", "fieldtype": "Data", "width": 180},
		{"label": _("Branch"), "fieldname": "branch", "fieldtype": "Data", "width": 140},
		{"label": _("Shift"), "fieldname": "shift", "fieldtype": "Data", "width": 180},
		{"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 140},
		{"label": _("Payroll Type"), "fieldname": "payroll_type", "fieldtype": "Data", "width": 120},
	]


def _get_schedule_columns():
	return [
		{"label": _("SchedDate"), "fieldname": "sched_date", "fieldtype": "Date", "width": 120},
		{"label": _("DayOfWeek"), "fieldname": "day_of_week", "fieldtype": "Data", "width": 120},
		{"label": _("SchedTimeStart"), "fieldname": "sched_time_start", "fieldtype": "Data", "width": 130},
		{"label": _("SchedTimeEnd"), "fieldname": "sched_time_end", "fieldtype": "Data", "width": 130},
		{"label": _("Time In"), "fieldname": "time_in", "fieldtype": "Data", "width": 110},
		{"label": _("Time Out"), "fieldname": "time_out", "fieldtype": "Data", "width": 110},
		{"label": _("Late (Hour)"), "fieldname": "late_hours", "fieldtype": "Float", "width": 110},
		{"label": _("OT Hours"), "fieldname": "valid_ot", "fieldtype": "Float", "width": 110},
		{"label": _("OT Type"), "fieldname": "overtime_type", "fieldtype": "Data", "width": 170},
		{"label": _("ND Hours"), "fieldname": "night_diff_hours", "fieldtype": "Float", "width": 110},
		{"label": _("OT Slip"), "fieldname": "authorization_no", "fieldtype": "Link", "options": "Overtime Slip", "width": 170},
		{"label": _("RestDay"), "fieldname": "rest_day", "fieldtype": "Date", "width": 110},
		{"label": _("HolidayType"), "fieldname": "holiday_type", "fieldtype": "Data", "width": 180},
		{"label": _("LeaveType"), "fieldname": "leave_type", "fieldtype": "Data", "width": 150},
		{"label": _("Department"), "fieldname": "department", "fieldtype": "Data", "width": 180},
		{"label": _("Shift"), "fieldname": "shift", "fieldtype": "Data", "width": 180},
	]


def _get_schedule_summary(rows):
	total_late = sum(frappe.utils.flt(row.get("late_hours")) for row in rows)
	total_ot = sum(frappe.utils.flt(row.get("valid_ot")) for row in rows)
	total_nd = sum(frappe.utils.flt(row.get("night_diff_hours")) for row in rows)
	absent = sum(1 for row in rows if _get_row_status(row) == "Absent")
	leave = sum(1 for row in rows if row.get("leave_type"))
	ot_breakdown = _get_ot_breakdown(rows)
	summary = [
		{"value": _format_hours(total_late), "indicator": "Orange", "label": _("Total Late"), "datatype": "Data"},
		{"value": _format_hours(total_ot), "indicator": "Blue", "label": _("Total OT"), "datatype": "Data"},
	]
	for ot_type, hours in sorted(ot_breakdown.items()):
		summary.append(
			{
				"value": _format_hours(hours),
				"indicator": "Blue",
				"label": _(ot_type),
				"datatype": "Data",
			}
		)
	if total_nd:
		summary.append(
			{
				"value": _format_hours(total_nd),
				"indicator": "Blue",
				"label": _("Night Diff"),
				"datatype": "Data",
			},
		)
	summary.extend(
		[
			{"value": absent, "indicator": "Red", "label": _("Absent"), "datatype": "Int"},
			{"value": leave, "indicator": "Purple", "label": _("Leave"), "datatype": "Int"},
		]
	)
	return summary


def _get_ot_breakdown(rows):
	breakdown = {}
	for row in rows:
		ot_hours = frappe.utils.flt(row.get("valid_ot"))
		if not ot_hours:
			continue

		ot_type = (row.get("overtime_type") or "").strip() or _("Unclassified OT")
		if "OT" not in ot_type.upper():
			ot_type = f"{ot_type} OT"
		breakdown[ot_type] = breakdown.get(ot_type, 0) + ot_hours
	return breakdown


def _get_row_status(row):
	is_holiday = bool(row.get("holiday_type") or row.get("rest_day"))
	if row.get("attendance_status") == "Absent":
		return "Absent"
	if row.get("sched_time_start") and not row.get("time_in") and not row.get("leave_type") and not is_holiday:
		return "Absent"
	return ""


def _format_hours(value):
	total_minutes = round(frappe.utils.flt(value) * 60)
	hours = total_minutes // 60
	minutes = total_minutes % 60
	if hours and minutes:
		return f"{hours}h {minutes}m"
	if hours:
		return f"{hours}h"
	return f"{minutes}m"
