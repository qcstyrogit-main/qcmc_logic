import frappe
from frappe import _
from frappe.utils import cint
from frappe.utils import add_days, getdate, now_datetime, today
from hrms.hr.doctype.shift_assignment_tool.shift_assignment_tool import create_shift_assignment


DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
DEFAULT_LATE_GRACE_PERIOD_MINUTES = 15


def _fmt_time(value):
	if not value:
		return ""

	if hasattr(value, "seconds"):
		total = value.seconds
		hour = total // 3600
		minute = (total % 3600) // 60
	else:
		hour = value.hour
		minute = value.minute

	suffix = "AM" if hour < 12 else "PM"
	hour_12 = hour % 12 if hour % 12 != 0 else 12
	return f"{hour_12}:{minute:02d} {suffix}"


def _get_late_grace_period_seconds(shift):
	grace_period = shift.late_entry_grace_period
	if grace_period in (None, ""):
		grace_period = DEFAULT_LATE_GRACE_PERIOD_MINUTES

	return cint(grace_period) * 60


def _get_late_hours(time_in, shift_start, grace_period_seconds):
	diff = time_in.hour * 3600 + time_in.minute * 60 - shift_start.seconds
	if diff <= grace_period_seconds:
		return 0.0

	return round((diff - grace_period_seconds) / 3600, 2)


def _normalize_date(value):
	return str(getdate(value or today()))


def _month_start(year, month_index):
	if month_index == 11:
		return getdate(f"{year + 1}-01-01").replace(day=1)
	return getdate(f"{year}-{month_index + 2:02d}-01").replace(day=1)


def _last_day(year, month_index):
	return add_days(_month_start(year, month_index), -1)


def get_cutoff_dates(cutoff_period=None, base_date=None):
	base = getdate(base_date or today())
	period = cutoff_period or "auto"
	if period == "Current Cutoff":
		period = "auto"
	elif period == "23-7 / Pay 15":
		period = "first"
	elif period == "8-22 / Pay 30":
		period = "second"

	if period == "auto":
		period = "first" if base.day <= 7 or base.day >= 23 else "second"

	if period == "first":
		if base.day <= 7:
			from_date = add_days(base.replace(day=1), -9)
			to_date = base.replace(day=7)
			pay_day = base.replace(day=15)
		else:
			next_month_start = _month_start(base.year, base.month - 1)
			from_date = base.replace(day=23)
			to_date = next_month_start.replace(day=7)
			pay_day = next_month_start.replace(day=15)
	else:
		from_date = base.replace(day=8)
		to_date = base.replace(day=22)
		pay_day = base.replace(day=min(30, _last_day(base.year, base.month - 1).day))

	return {
		"cutoff_period": period,
		"from_date": str(from_date),
		"to_date": str(to_date),
		"pay_day": str(pay_day),
	}


@frappe.whitelist()
def get_payroll_period_dates(payroll_period):
	pay_day = getdate(payroll_period)

	if pay_day.day == 15:
		from_date = add_days(pay_day.replace(day=1), -9)
		to_date = pay_day.replace(day=7)
	else:
		from_date = pay_day.replace(day=8)
		to_date = pay_day.replace(day=22)

	return {
		"payroll_period": str(pay_day),
		"pay_day": str(pay_day),
		"from_date": str(from_date),
		"to_date": str(to_date),
	}


def _get_holiday_map(holiday_list, from_date, to_date):
	holiday_map = {}
	if not holiday_list:
		return holiday_map

	for holiday in frappe.get_all(
		"Holiday",
		filters={"parent": holiday_list, "holiday_date": ["between", [from_date, to_date]]},
		fields=["holiday_date", "description"],
	):
		holiday_map[str(holiday.holiday_date)] = holiday
	return holiday_map


def _get_leave_map(employee_names, from_date, to_date):
	leave_map = {}
	if not employee_names:
		return leave_map

	for leave in frappe.get_all(
		"Leave Application",
		filters={
			"employee": ["in", employee_names],
			"status": "Approved",
			"from_date": ["<=", to_date],
			"to_date": [">=", from_date],
		},
		fields=["employee", "from_date", "to_date", "leave_type"],
	):
		days = frappe.utils.date_diff(str(leave.to_date), str(leave.from_date))
		for index in range(days + 1):
			leave_date = str(add_days(str(leave.from_date), index))
			if from_date <= leave_date <= to_date:
				leave_map[(leave.employee, leave_date)] = leave.leave_type
	return leave_map


def _get_authorization_maps(attendance_names, employee_names, from_date, to_date):
	authorization_map = {}
	slip_names_by_employee_date = {}
	overtime_by_attendance = {}
	overtime_by_employee_date = {}

	if not (
		frappe.db.exists("DocType", "Overtime Slip")
		and frappe.db.exists("DocType", "Overtime Details")
	):
		return authorization_map, slip_names_by_employee_date, overtime_by_attendance, overtime_by_employee_date

	if attendance_names:
		details = frappe.get_all(
			"Overtime Details",
			filters={"reference_document": ["in", attendance_names]},
			fields=["parent", "reference_document", "overtime_duration"],
			order_by="idx asc",
		)
		parents = []
		for detail in details:
			if detail.parent and detail.parent not in parents:
				parents.append(detail.parent)

		submitted_slips = {}
		if parents:
			for slip in frappe.get_all(
				"Overtime Slip",
				filters={"name": ["in", parents], "docstatus": 1},
				fields=["name"],
			):
				submitted_slips[slip.name] = slip.name

		for detail in details:
			if detail.parent in submitted_slips and detail.reference_document not in authorization_map:
				authorization_map[detail.reference_document] = detail.parent
			if detail.parent in submitted_slips:
				overtime_by_attendance[detail.reference_document] = round(
					float(detail.overtime_duration or 0), 2
				)

	date_details = frappe.get_all(
		"Overtime Details",
		filters={"date": ["between", [from_date, to_date]]},
		fields=["parent", "date", "overtime_duration"],
		order_by="idx asc",
	)
	parents = []
	for detail in date_details:
		if detail.parent and detail.parent not in parents:
			parents.append(detail.parent)

	if parents:
		for slip in frappe.get_all(
			"Overtime Slip",
			filters={"name": ["in", parents], "employee": ["in", employee_names], "docstatus": 1},
			fields=["name", "employee"],
		):
			for detail in date_details:
				if detail.parent == slip.name:
					key = (slip.employee, str(detail.date))
					if key not in slip_names_by_employee_date:
						slip_names_by_employee_date[key] = slip.name
					overtime_by_employee_date[key] = round(float(detail.overtime_duration or 0), 2)

	return authorization_map, slip_names_by_employee_date, overtime_by_attendance, overtime_by_employee_date


@frappe.whitelist()
def debug_overtime_maps(attendance_names=None, employee_names=None, from_date=None, to_date=None):
	attendance_names = frappe.parse_json(attendance_names) if isinstance(attendance_names, str) else attendance_names
	employee_names = frappe.parse_json(employee_names) if isinstance(employee_names, str) else employee_names
	maps = _get_authorization_maps(attendance_names or [], employee_names or [], from_date, to_date)
	return {
		"authorization_map": maps[0],
		"slip_names_by_employee_date": {f"{key[0]}|{key[1]}": value for key, value in maps[1].items()},
		"overtime_by_attendance": maps[2],
		"overtime_by_employee_date": {f"{key[0]}|{key[1]}": value for key, value in maps[3].items()},
	}


def _resolve_period(from_date=None, to_date=None, cutoff_period=None, payroll_period=None):
	if payroll_period:
		payroll_dates = get_payroll_period_dates(payroll_period)
		from_date = payroll_dates["from_date"]
		to_date = payroll_dates["to_date"]
	elif not from_date or not to_date:
		cutoff = get_cutoff_dates(cutoff_period)
		from_date = cutoff["from_date"]
		to_date = cutoff["to_date"]
	else:
		from_date = _normalize_date(from_date)
		to_date = _normalize_date(to_date)

	return {
		"from_date": from_date,
		"to_date": to_date,
		"pay_day": payroll_dates["pay_day"] if payroll_period else None,
		"payroll_period": payroll_dates["payroll_period"] if payroll_period else None,
	}


def _get_employee_company(employee):
	company = frappe.db.get_value("Employee", employee, "company")
	if not company:
		frappe.throw(_("Employee {0} was not found.").format(frappe.bold(employee)))

	return company


@frappe.whitelist()
def create_current_period_shift_assignment(employee, shift_type, from_date=None, to_date=None, payroll_period=None):
	if not employee:
		frappe.throw(_("Please select an employee."))
	if not shift_type:
		frappe.throw(_("Please select a Shift Type."))

	period = _resolve_period(from_date, to_date, payroll_period=payroll_period)
	assignment = create_shift_assignment(
		employee=employee,
		company=_get_employee_company(employee),
		shift_type=shift_type,
		start_date=period["from_date"],
		end_date=period["to_date"],
		status="Active",
	)

	return {
		"name": assignment.name,
		"from_date": period["from_date"],
		"to_date": period["to_date"],
	}


@frappe.whitelist()
def copy_previous_period_shift_schedule(employee, from_date=None, to_date=None, payroll_period=None):
	if not employee:
		frappe.throw(_("Please select an employee."))

	period = _resolve_period(from_date, to_date, payroll_period=payroll_period)
	current_from = period["from_date"]
	current_to = period["to_date"]
	period_days = frappe.utils.date_diff(current_to, current_from) + 1
	previous_to = str(add_days(current_from, -1))
	previous_from = str(add_days(previous_to, -(period_days - 1)))

	previous_assignments = frappe.get_all(
		"Shift Assignment",
		filters=[
			["employee", "=", employee],
			["docstatus", "=", 1],
			["status", "=", "Active"],
			["start_date", "<=", previous_to],
		],
		or_filters=[
			["end_date", ">=", previous_from],
			["end_date", "is", "not set"],
		],
		fields=["shift_type", "shift_location", "start_date", "end_date"],
		order_by="start_date asc",
	)

	if not previous_assignments:
		frappe.throw(
			_("No Shift Assignment was found for {0} in the previous payroll period {1} to {2}.").format(
				frappe.bold(employee),
				frappe.bold(previous_from),
				frappe.bold(previous_to),
			)
		)

	company = _get_employee_company(employee)
	created = []
	for previous in previous_assignments:
		source_start = max(str(previous.start_date), previous_from)
		source_end = min(str(previous.end_date or previous_to), previous_to)
		offset = frappe.utils.date_diff(source_start, previous_from)
		duration = frappe.utils.date_diff(source_end, source_start)
		target_start = str(add_days(current_from, offset))
		target_end = str(add_days(target_start, duration))
		if target_start > current_to:
			continue
		if target_end > current_to:
			target_end = current_to

		assignment = create_shift_assignment(
			employee=employee,
			company=company,
			shift_type=previous.shift_type,
			start_date=target_start,
			end_date=target_end,
			status="Active",
			shift_location=previous.shift_location,
		)
		created.append(assignment.name)

	return {
		"created": created,
		"count": len(created),
		"previous_from_date": previous_from,
		"previous_to_date": previous_to,
		"from_date": current_from,
		"to_date": current_to,
	}


def _get_schedule_context(from_date=None, to_date=None, cutoff_period=None, company=None, payroll_period=None):
	period = _resolve_period(from_date, to_date, cutoff_period, payroll_period)
	from_date = period["from_date"]
	to_date = period["to_date"]

	employee_filters = {"status": "Active"}
	if company:
		employee_filters["company"] = company

	employees = frappe.get_all(
		"Employee",
		filters=employee_filters,
		fields=["name", "employee_name", "department", "company", "default_shift", "holiday_list"],
		order_by="employee_name asc",
	)

	all_employee_names = [employee.name for employee in employees]
	shift_assignment_map = {}
	employees_with_shift_assignment = {}
	employees_with_shift_schedule_assignment = {}
	employees_with_overtime_slip = {}
	if all_employee_names and frappe.db.exists("DocType", "Shift Assignment"):
		for assignment in frappe.get_all(
			"Shift Assignment",
			filters=[
				["employee", "in", all_employee_names],
				["docstatus", "=", 1],
				["status", "=", "Active"],
				["start_date", "<=", to_date],
			],
			or_filters=[
				["end_date", ">=", from_date],
				["end_date", "is", "not set"],
			],
			fields=["employee", "shift_type", "start_date", "end_date"],
			order_by="start_date asc",
		):
			employees_with_shift_assignment[assignment.employee] = 1
			start_date = max(str(assignment.start_date), from_date)
			end_date = min(str(assignment.end_date or to_date), to_date)
			days = frappe.utils.date_diff(end_date, start_date)
			for index in range(days + 1):
				sched_date = str(add_days(start_date, index))
				shift_assignment_map[(assignment.employee, sched_date)] = assignment.shift_type

	if all_employee_names and frappe.db.exists("DocType", "Shift Schedule Assignment"):
		for assignment in frappe.get_all(
			"Shift Schedule Assignment",
			filters={
				"employee": ["in", all_employee_names],
				"enabled": 1,
				"shift_status": "Active",
			},
			fields=["employee"],
		):
			employees_with_shift_schedule_assignment[assignment.employee] = 1

	if all_employee_names and frappe.db.exists("DocType", "Overtime Slip") and frappe.db.exists(
		"DocType", "Overtime Details"
	):
		overtime_details = frappe.get_all(
			"Overtime Details",
			filters={"date": ["between", [from_date, to_date]]},
			fields=["parent"],
		)
		overtime_parents = []
		for detail in overtime_details:
			if detail.parent and detail.parent not in overtime_parents:
				overtime_parents.append(detail.parent)

		if overtime_parents:
			for slip in frappe.get_all(
				"Overtime Slip",
				filters={
					"name": ["in", overtime_parents],
					"employee": ["in", all_employee_names],
					"docstatus": 1,
				},
				fields=["employee"],
			):
				employees_with_overtime_slip[slip.employee] = 1

	scheduled_employees = []
	skipped_employees = []
	employee_lookup = {}
	employee_summaries = []
	for employee in employees:
		has_shift_setup = bool(
			employee.default_shift
			or employees_with_shift_assignment.get(employee.name)
			or employees_with_shift_schedule_assignment.get(employee.name)
			or employees_with_overtime_slip.get(employee.name)
		)
		status = "Ready" if has_shift_setup else "No Shift Setup"
		employee_dict = {
			"name": employee.name,
			"employee_name": employee.employee_name,
			"department": employee.department,
			"company": employee.company,
			"default_shift": employee.default_shift,
			"holiday_list": employee.holiday_list,
			"has_shift_setup": has_shift_setup,
			"status": status,
		}
		employee_lookup[employee.name] = employee_dict
		employee_summaries.append(
			{
				"employee": employee.name,
				"employee_name": employee.employee_name,
				"department": employee.department,
				"default_shift": employee.default_shift or "",
				"status": status,
			}
		)
		if (
			employee.default_shift
			or employees_with_shift_assignment.get(employee.name)
			or employees_with_shift_schedule_assignment.get(employee.name)
			or employees_with_overtime_slip.get(employee.name)
		):
			scheduled_employees.append(employee_dict)
		else:
			skipped_employees.append(
				{"employee": employee.name, "employee_name": employee.employee_name}
			)

	employee_names = [employee["name"] for employee in scheduled_employees]

	attendance_map = {}
	attendance_names = []
	if employee_names:
		for attendance in frappe.get_all(
			"Attendance",
			filters={
				"employee": ["in", employee_names],
				"attendance_date": ["between", [from_date, to_date]],
				"docstatus": ["!=", 2],
			},
			fields=[
				"name",
				"employee",
				"attendance_date",
				"in_time",
				"out_time",
				"shift",
				"leave_type",
				"actual_overtime_duration",
			],
			order_by="attendance_date asc",
		):
			key = (attendance.employee, str(attendance.attendance_date))
			attendance_map[key] = attendance
			attendance_names.append(attendance.name)

	shift_map = {}
	for shift in frappe.get_all(
		"Shift Type",
		fields=["name", "start_time", "end_time", "late_entry_grace_period"],
	):
		shift_map[shift.name] = shift

	company_holiday_lists = {}
	holiday_maps = {}
	for employee in scheduled_employees:
		if employee["company"] not in company_holiday_lists:
			company_holiday_lists[employee["company"]] = frappe.db.get_value(
				"Company", employee["company"], "default_holiday_list"
			)
		holiday_list = employee["holiday_list"] or company_holiday_lists.get(employee["company"])
		if holiday_list not in holiday_maps:
			holiday_maps[holiday_list] = _get_holiday_map(holiday_list, from_date, to_date)

	leave_map = _get_leave_map(employee_names, from_date, to_date)
	(
		authorization_map,
		slip_names_by_employee_date,
		overtime_by_attendance,
		overtime_by_employee_date,
	) = _get_authorization_maps(
		attendance_names, employee_names, from_date, to_date
	)

	return {
		"from_date": from_date,
		"to_date": to_date,
		"pay_day": period["pay_day"],
		"payroll_period": period["payroll_period"],
		"employees": employees,
		"employee_lookup": employee_lookup,
		"employee_summaries": employee_summaries,
		"scheduled_employees": scheduled_employees,
		"skipped_employees": skipped_employees,
		"shift_assignment_map": shift_assignment_map,
		"attendance_map": attendance_map,
		"shift_map": shift_map,
		"company_holiday_lists": company_holiday_lists,
		"holiday_maps": holiday_maps,
		"leave_map": leave_map,
		"authorization_map": authorization_map,
		"slip_names_by_employee_date": slip_names_by_employee_date,
		"overtime_by_attendance": overtime_by_attendance,
		"overtime_by_employee_date": overtime_by_employee_date,
	}


def _build_employee_rows(employee, context):
	rows = []
	from_date = context["from_date"]
	to_date = context["to_date"]
	total_days = frappe.utils.date_diff(to_date, from_date)
	holiday_list = employee["holiday_list"] or context["company_holiday_lists"].get(employee["company"])
	holiday_map = context["holiday_maps"].get(holiday_list, {})

	for day_index in range(total_days + 1):
		sched_date = str(add_days(from_date, day_index))
		current = getdate(sched_date)
		day_name = DAYS[current.weekday()]
		is_weekend = current.weekday() >= 5
		holiday = holiday_map.get(sched_date)
		attendance = context["attendance_map"].get((employee["name"], sched_date))
		shift_name = context["shift_assignment_map"].get((employee["name"], sched_date)) or employee["default_shift"]
		shift = context["shift_map"].get(shift_name)

		sched_start = ""
		sched_end = ""
		if shift and not is_weekend and not holiday:
			sched_start = _fmt_time(shift.start_time)
			sched_end = _fmt_time(shift.end_time)

		late = 0.0
		if attendance and attendance.in_time and shift and shift.start_time and not is_weekend and not holiday:
			late = _get_late_hours(
				attendance.in_time,
				shift.start_time,
				_get_late_grace_period_seconds(shift),
			)

		valid_ot = 0.0
		if attendance:
			valid_ot = context["overtime_by_attendance"].get(attendance.name) or context[
				"overtime_by_employee_date"
			].get((employee["name"], sched_date), 0.0)

		leave_type = context["leave_map"].get((employee["name"], sched_date)) or (
			attendance.leave_type if attendance else ""
		)
		authorization_no = ""
		if attendance:
			authorization_no = context["authorization_map"].get(attendance.name) or context[
				"slip_names_by_employee_date"
			].get((employee["name"], sched_date)) or ""

		rows.append(
			{
				"employee": employee["name"],
				"employee_name": employee["employee_name"],
				"department": employee["department"],
				"shift": shift_name,
				"sched_date": sched_date,
				"day_of_week": day_name,
				"sched_time_start": sched_start,
				"sched_time_end": sched_end,
				"time_in": _fmt_time(attendance.in_time) if attendance and attendance.in_time else "",
				"time_out": _fmt_time(attendance.out_time) if attendance and attendance.out_time else "",
				"attendance_status": attendance.status if attendance else "",
				"late_hours": late,
				"valid_ot": valid_ot,
				"authorization_no": authorization_no,
				"rest_day": sched_date if is_weekend or holiday else "",
				"holiday_type": (holiday.description if holiday else "Weekly Off")
				if is_weekend or holiday
				else "",
				"leave_type": leave_type or "",
			}
		)

	return rows


def _is_absent_row(row):
	is_holiday = bool(row.get("holiday_type") or row.get("rest_day"))
	return row.get("attendance_status") == "Absent" or (
		row.get("sched_time_start")
		and not row.get("time_in")
		and not row.get("leave_type")
		and not is_holiday
	)


def _summarize_exception_employees(context):
	exception_keys = ["late", "absent", "no_shift_setup", "missing_time_out", "with_ot"]
	employees_by_exception = {key: {} for key in exception_keys}

	for employee in context["skipped_employees"]:
		employees_by_exception["no_shift_setup"][employee["employee"]] = {
			"employee": employee["employee"],
			"employee_name": employee["employee_name"],
		}

	for employee in context["scheduled_employees"]:
		rows = _build_employee_rows(employee, context)
		employee_summary = {
			"employee": employee["name"],
			"employee_name": employee["employee_name"],
		}
		if any(float(row.get("late_hours") or 0) > 0 for row in rows):
			employees_by_exception["late"][employee["name"]] = employee_summary
		if any(_is_absent_row(row) for row in rows):
			employees_by_exception["absent"][employee["name"]] = employee_summary
		if any(row.get("time_in") and not row.get("time_out") for row in rows):
			employees_by_exception["missing_time_out"][employee["name"]] = employee_summary
		if any(float(row.get("valid_ot") or 0) > 0 for row in rows):
			employees_by_exception["with_ot"][employee["name"]] = employee_summary

	return {
		key: list(employees.values()) for key, employees in employees_by_exception.items()
	}


@frappe.whitelist()
def get_exception_dashboard(from_date=None, to_date=None, cutoff_period=None, company=None, payroll_period=None):
	context = _get_schedule_context(from_date, to_date, cutoff_period, company, payroll_period)
	employees_by_exception = _summarize_exception_employees(context)
	return {
		"from_date": context["from_date"],
		"to_date": context["to_date"],
		"counts": {
			key: len(employees) for key, employees in employees_by_exception.items()
		},
		"employees": employees_by_exception,
	}


@frappe.whitelist()
def get_employee_schedule(employee, from_date=None, to_date=None, cutoff_period=None, company=None, payroll_period=None):
	context = _get_schedule_context(from_date, to_date, cutoff_period, company, payroll_period)
	employee_data = context["employee_lookup"].get(employee)
	if not employee_data:
		frappe.throw("Employee not found for the selected filters.")

	return {
		"employee": employee_data["name"],
		"employee_name": employee_data["employee_name"],
		"department": employee_data["department"],
		"status": employee_data["status"],
		"rows": _build_employee_rows(employee_data, context) if employee_data["has_shift_setup"] else [],
	}


@frappe.whitelist()
def get_employee_directory(from_date=None, to_date=None, cutoff_period=None, company=None, payroll_period=None):
	context = _get_schedule_context(from_date, to_date, cutoff_period, company, payroll_period)
	return {
		"from_date": context["from_date"],
		"to_date": context["to_date"],
		"pay_day": context["pay_day"],
		"payroll_period": context["payroll_period"],
		"employees": context["employee_summaries"],
		"skipped_employees": context["skipped_employees"],
		"total_employees": len(context["employees"]),
		"scheduled_employees": len(context["scheduled_employees"]),
	}


@frappe.whitelist()
def generate(from_date=None, to_date=None, cutoff_period=None, company=None, payroll_period=None):
	context = _get_schedule_context(from_date, to_date, cutoff_period, company, payroll_period)
	default_employee = next(
		(employee["employee"] for employee in context["employee_summaries"] if employee["status"] == "Ready"),
		context["employee_summaries"][0]["employee"] if context["employee_summaries"] else None,
	)
	default_rows = []
	if default_employee and context["employee_lookup"][default_employee]["has_shift_setup"]:
		default_rows = _build_employee_rows(context["employee_lookup"][default_employee], context)

	return {
		"generated_on": now_datetime(),
		"from_date": context["from_date"],
		"to_date": context["to_date"],
		"pay_day": context["pay_day"],
		"payroll_period": context["payroll_period"],
		"rows": default_rows,
		"default_employee": default_employee,
		"employees": context["employee_summaries"],
		"skipped_employees": context["skipped_employees"],
		"total_employees": len(context["employees"]),
		"scheduled_employees": len(context["scheduled_employees"]),
		"generated_rows": len(default_rows),
	}
