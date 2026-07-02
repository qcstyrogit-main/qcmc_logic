from datetime import datetime, time, timedelta

import frappe
from frappe.utils import add_days, cint, flt, getdate

from qcmc_logic.customs.rest_day import get_employee_roster_work_days, is_rest_day_from_work_days


DEFAULT_LATE_GRACE_PERIOD_MINUTES = 15
NIGHT_DIFFERENTIAL_COMPONENT = "Nightshift Differential"
NIGHT_DIFFERENTIAL_RATE = 0.10
NIGHT_DIFFERENTIAL_START_HOUR = 22
NIGHT_DIFFERENTIAL_END_HOUR = 6


def apply_attendance_late(doc, method=None):
	if not (doc.employee and doc.start_date and doc.end_date):
		return

	if frappe.get_meta("Salary Slip").has_field("custom_undertimelate"):
		late_hours = calculate_attendance_late_hours(
			doc.employee,
			doc.start_date,
			doc.end_date,
			doc.company,
		)
		doc.custom_undertimelate = late_hours

		if frappe.get_meta("Salary Slip").has_field("custom_total_undertimelate"):
			doc.custom_total_undertimelate = (
				get_previous_attendance_late_hours(doc.employee, doc.start_date) + late_hours
			)

	apply_weekly_daily_rate_components(doc)
	apply_night_differential(doc)


def apply_weekly_daily_rate_components(doc):
	if not is_weekly_employee(doc):
		return

	daily_rate = get_employee_daily_rate(doc.employee)
	if not daily_rate:
		return

	set_salary_component_amount(
		doc,
		"earnings",
		"Regular Hours",
		flt(daily_rate * flt(doc.payment_days), 2),
	)
	set_salary_component_amount(
		doc,
		"deductions",
		"Absences",
		flt(daily_rate * flt(doc.absent_days), 2),
	)
	set_salary_component_amount(
		doc,
		"deductions",
		"Tardy",
		flt(flt(doc.get("custom_undertimelate")) * daily_rate / 8, 2),
	)


def apply_night_differential(doc):
	if not frappe.db.exists("Salary Component", NIGHT_DIFFERENTIAL_COMPONENT):
		return

	amount = calculate_night_differential_amount(doc)
	set_salary_component_amount(
		doc,
		"earnings",
		NIGHT_DIFFERENTIAL_COMPONENT,
		amount,
	)


def calculate_night_differential_amount(salary_slip):
	entries = calculate_night_differential_entries(
		salary_slip.employee,
		salary_slip.start_date,
		salary_slip.end_date,
		salary_slip.company,
	)
	if not entries:
		return 0.0

	daily_rate = get_salary_slip_daily_rate(salary_slip)
	if not daily_rate:
		return 0.0

	total = 0.0
	for entry in entries:
		standard_hours = flt(entry.get("standard_working_hours")) or 8
		hourly_rate = daily_rate / standard_hours if standard_hours else 0
		total += flt(entry.get("night_diff_hours")) * hourly_rate * NIGHT_DIFFERENTIAL_RATE

	return flt(total, 2)


def get_payslip_component_hours(salary_slip_name):
	salary_slip = frappe.get_doc("Salary Slip", salary_slip_name)
	hours = {}
	hours.update(_get_overtime_component_hours(salary_slip))

	night_diff_hours = sum(
		flt(row.get("night_diff_hours"))
		for row in calculate_night_differential_entries(
			salary_slip.employee,
			salary_slip.start_date,
			salary_slip.end_date,
			salary_slip.company,
		)
	)
	if night_diff_hours:
		hours[NIGHT_DIFFERENTIAL_COMPONENT] = flt(night_diff_hours, 2)

	return hours


def _get_overtime_component_hours(salary_slip):
	additional_salary_names = [
		row.additional_salary
		for row in salary_slip.get("earnings", [])
		if row.get("additional_salary")
	]
	if not additional_salary_names:
		return {}

	additional_salaries = frappe.get_all(
		"Additional Salary",
		filters={
			"name": ["in", additional_salary_names],
			"ref_doctype": "Overtime Slip",
			"ref_docname": ["is", "set"],
		},
		fields=["salary_component", "ref_docname"],
	)
	if not additional_salaries:
		return {}

	component_by_overtime_type = {
		row.name: row.overtime_salary_component
		for row in frappe.get_all(
			"Overtime Type",
			filters={"overtime_salary_component": ["!=", ""]},
			fields=["name", "overtime_salary_component"],
		)
	}
	components = {row.salary_component for row in additional_salaries}
	overtime_slips = {row.ref_docname for row in additional_salaries}
	hours = {component: 0.0 for component in components}

	for detail in frappe.get_all(
		"Overtime Details",
		filters={"parent": ["in", list(overtime_slips)]},
		fields=["overtime_type", "overtime_duration"],
		limit_page_length=50000,
	):
		component = component_by_overtime_type.get(detail.overtime_type)
		if component in hours:
			hours[component] += flt(detail.overtime_duration)

	return {component: flt(value, 2) for component, value in hours.items() if flt(value) > 0}


def install_qc_salary_slip_hours_print_format():
	print_format = frappe.get_doc("Print Format", "QC Salary Slip")
	html = print_format.html or ""
	html = html.replace(
		"  table.comp-table th.amount { text-align: right; }\n",
		"  table.comp-table th.amount { text-align: right; }\n"
		"  table.comp-table th.hours { text-align: right; width: 54px; }\n",
	)
	html = html.replace(
		"  table.comp-table td.amount { text-align: right; }\n",
		"  table.comp-table td.amount { text-align: right; }\n"
		"  table.comp-table td.hours { text-align: right; white-space: nowrap; }\n",
	)
	html = html.replace(
		"{% endfor %}\n\n<div class=\"payslip-wrap\">",
		"{% endfor %}\n\n"
		"<div class=\"payslip-wrap\">",
	)
	html = html.replace(
		"{% endfor %}\n\n"
		"{% set component_hours = frappe.get_attr(\"qcmc_logic.customs.salary_slip_attendance.get_payslip_component_hours\")(doc.name) %}\n\n"
		"<div class=\"payslip-wrap\">",
		"{% endfor %}\n\n"
		"<div class=\"payslip-wrap\">",
	)
	html = html.replace(
		"            <th>Component</th>\n"
		"            <th class=\"amount\">Amount (PHP)</th>",
		"            <th>Component</th>\n"
		"            <th class=\"hours\">Hours</th>\n"
		"            <th class=\"amount\">Amount (PHP)</th>",
		1,
	)
	html = html.replace(
		"            <td>{{ e.salary_component }}</td>\n"
		"            <td class=\"amount\">{{ frappe.format(e.amount, {'fieldtype': 'Currency'}) }}</td>",
		"            {% set earning_hours = 0 %}\n"
		"            {% if e.additional_salary %}\n"
		"              {% set ot_hours = frappe.db.sql(\"select coalesce(sum(od.overtime_duration), 0) as hours from `tabAdditional Salary` ads join `tabOvertime Details` od on od.parent = ads.ref_docname join `tabOvertime Type` ot on ot.name = od.overtime_type where ads.name = %s and ads.ref_doctype = 'Overtime Slip' and ot.overtime_salary_component = %s\", (e.additional_salary, e.salary_component), as_dict=True) %}\n"
		"              {% set earning_hours = ot_hours[0].hours if ot_hours else 0 %}\n"
		"            {% elif e.salary_component == \"Nightshift Differential\" %}\n"
		"              {% set nd_hours = frappe.db.sql(\"select coalesce(round(sum(greatest(0, timestampdiff(second, greatest(in_time, timestamp(attendance_date, '22:00:00')), least(case when out_time < in_time then date_add(out_time, interval 1 day) else out_time end, timestamp(date_add(attendance_date, interval 1 day), '06:00:00'))))) / 3600, 2), 0) as hours from `tabAttendance` where employee = %s and attendance_date between %s and %s and docstatus = 1 and status != 'Absent' and in_time is not null and out_time is not null\", (doc.employee, doc.start_date, doc.end_date), as_dict=True) %}\n"
		"              {% set earning_hours = nd_hours[0].hours if nd_hours else 0 %}\n"
		"            {% endif %}\n"
		"            <td>{{ e.salary_component }}</td>\n"
		"            <td class=\"hours\">{% if earning_hours %}{{ \"%.2f\" % (earning_hours | float) }}{% endif %}</td>\n"
		"            <td class=\"amount\">{{ frappe.format(e.amount, {'fieldtype': 'Currency'}) }}</td>",
		1,
	)
	html = html.replace(
		"            <td>{{ e.salary_component }}</td>\n"
		"            <td class=\"hours\">{% if component_hours.get(e.salary_component) %}{{ \"%.2f\" % component_hours.get(e.salary_component) }}{% endif %}</td>\n"
		"            <td class=\"amount\">{{ frappe.format(e.amount, {'fieldtype': 'Currency'}) }}</td>",
		"            {% set earning_hours = 0 %}\n"
		"            {% if e.additional_salary %}\n"
		"              {% set ot_hours = frappe.db.sql(\"select coalesce(sum(od.overtime_duration), 0) as hours from `tabAdditional Salary` ads join `tabOvertime Details` od on od.parent = ads.ref_docname join `tabOvertime Type` ot on ot.name = od.overtime_type where ads.name = %s and ads.ref_doctype = 'Overtime Slip' and ot.overtime_salary_component = %s\", (e.additional_salary, e.salary_component), as_dict=True) %}\n"
		"              {% set earning_hours = ot_hours[0].hours if ot_hours else 0 %}\n"
		"            {% elif e.salary_component == \"Nightshift Differential\" %}\n"
		"              {% set nd_hours = frappe.db.sql(\"select coalesce(round(sum(greatest(0, timestampdiff(second, greatest(in_time, timestamp(attendance_date, '22:00:00')), least(case when out_time < in_time then date_add(out_time, interval 1 day) else out_time end, timestamp(date_add(attendance_date, interval 1 day), '06:00:00'))))) / 3600, 2), 0) as hours from `tabAttendance` where employee = %s and attendance_date between %s and %s and docstatus = 1 and status != 'Absent' and in_time is not null and out_time is not null\", (doc.employee, doc.start_date, doc.end_date), as_dict=True) %}\n"
		"              {% set earning_hours = nd_hours[0].hours if nd_hours else 0 %}\n"
		"            {% endif %}\n"
		"            <td>{{ e.salary_component }}</td>\n"
		"            <td class=\"hours\">{% if earning_hours %}{{ \"%.2f\" % (earning_hours | float) }}{% endif %}</td>\n"
		"            <td class=\"amount\">{{ frappe.format(e.amount, {'fieldtype': 'Currency'}) }}</td>",
		1,
	)
	html = html.replace(
		"            <td>Gross Pay</td>\n"
		"            <td class=\"amount\">{{ frappe.format(doc.gross_pay, {'fieldtype': 'Currency'}) }}</td>",
		"            <td colspan=\"2\">Gross Pay</td>\n"
		"            <td class=\"amount\">{{ frappe.format(doc.gross_pay, {'fieldtype': 'Currency'}) }}</td>",
		1,
	)
	html = html.replace(
		"      <div class=\"section-title\">Deductions</div>\n"
		"      <table class=\"comp-table\">\n"
		"        <thead>\n"
		"          <tr>\n"
		"            <th>Component</th>\n"
		"            <th class=\"hours\">Hours</th>\n"
		"            <th class=\"amount\">Amount (PHP)</th>",
		"      <div class=\"section-title\">Deductions</div>\n"
		"      <table class=\"comp-table\">\n"
		"        <thead>\n"
		"          <tr>\n"
		"            <th>Component</th>\n"
		"            <th class=\"amount\">Amount (PHP)</th>",
	)
	print_format.html = html
	print_format.save(ignore_permissions=True)
	frappe.db.commit()
	return "QC Salary Slip print format updated with earnings hours."


def calculate_night_differential_entries(employee, start_date, end_date, company=None):
	start_date = str(getdate(start_date))
	end_date = str(getdate(end_date))
	employee_doc = frappe.db.get_value(
		"Employee",
		employee,
		["company", "default_shift", "holiday_list"],
		as_dict=True,
	)
	if not employee_doc:
		return []

	shift_assignments = _get_shift_assignments(employee, start_date, end_date)
	shift_map = _get_shift_map()
	checkins_by_date = _get_checkin_pairs_by_date(employee, start_date, end_date)

	entries_by_date = {}
	for attendance in frappe.get_all(
		"Attendance",
		filters={
			"employee": employee,
			"attendance_date": ["between", [start_date, end_date]],
			"docstatus": 1,
			"status": ["!=", "Absent"],
		},
		fields=[
			"attendance_date",
			"in_time",
			"out_time",
			"shift",
			"standard_working_hours",
		],
		order_by="attendance_date asc",
	):
		attendance_date = str(attendance.attendance_date)
		time_in = attendance.in_time
		time_out = attendance.out_time
		if not (time_in and time_out):
			pair = checkins_by_date.get(attendance_date) or {}
			time_in = time_in or pair.get("in_time")
			time_out = time_out or pair.get("out_time")

		if not (time_in and time_out):
			continue

		shift_name = (
			shift_assignments.get(attendance_date)
			or attendance.shift
			or employee_doc.default_shift
		)
		standard_hours = (
			flt(attendance.standard_working_hours)
			or _get_shift_hours(shift_map.get(shift_name))
			or 8
		)
		night_diff_hours = _get_night_differential_hours(time_in, time_out)
		if night_diff_hours:
			entries_by_date[attendance_date] = {
				"date": attendance_date,
				"night_diff_hours": night_diff_hours,
				"standard_working_hours": standard_hours,
			}

	for checkin_date, pair in checkins_by_date.items():
		if checkin_date in entries_by_date:
			continue
		if not (pair.get("in_time") and pair.get("out_time")):
			continue

		shift_name = shift_assignments.get(checkin_date) or pair.get("shift") or employee_doc.default_shift
		night_diff_hours = _get_night_differential_hours(pair.get("in_time"), pair.get("out_time"))
		if night_diff_hours:
			entries_by_date[checkin_date] = {
				"date": checkin_date,
				"night_diff_hours": night_diff_hours,
				"standard_working_hours": _get_shift_hours(shift_map.get(shift_name)) or 8,
			}

	return [entries_by_date[key] for key in sorted(entries_by_date)]


def get_previous_attendance_late_hours(employee, start_date):
	start_date = getdate(start_date)
	payroll_period = frappe.get_all(
		"Payroll Period",
		filters={
			"start_date": ["<=", start_date],
			"end_date": [">=", start_date],
		},
		fields=["start_date"],
		limit=1,
	)
	if not payroll_period:
		return 0.0

	period_start = getdate(payroll_period[0].start_date)
	if period_start >= start_date:
		return 0.0

	return calculate_attendance_late_hours(employee, period_start, add_days(start_date, -1))


def calculate_attendance_late_hours(employee, start_date, end_date, company=None):
	start_date = str(getdate(start_date))
	end_date = str(getdate(end_date))
	employee_doc = frappe.db.get_value(
		"Employee",
		employee,
		["company", "default_shift", "holiday_list"],
		as_dict=True,
	)
	if not employee_doc:
		return 0.0

	holiday_list = employee_doc.holiday_list or frappe.db.get_value(
		"Company", company or employee_doc.company, "default_holiday_list"
	)
	holiday_dates = _get_holiday_dates(holiday_list, start_date, end_date)
	shift_assignments = _get_shift_assignments(employee, start_date, end_date)
	roster_work_days = get_employee_roster_work_days(employee, start_date, end_date)

	shift_map = {
		shift.name: shift
		for shift in frappe.get_all(
			"Shift Type",
			fields=["name", "start_time", "late_entry_grace_period"],
		)
	}

	total = 0.0
	dates_with_attendance = set()
	for attendance in frappe.get_all(
		"Attendance",
		filters={
			"employee": employee,
			"attendance_date": ["between", [start_date, end_date]],
			"docstatus": 1,
			"status": ["!=", "Absent"],
		},
		fields=["attendance_date", "in_time", "shift"],
		order_by="attendance_date asc",
	):
		dates_with_attendance.add(str(attendance.attendance_date))
		if not attendance.in_time:
			continue

		attendance_date = str(attendance.attendance_date)
		shift_name = (
			shift_assignments.get(attendance_date)
			or attendance.shift
			or employee_doc.default_shift
		)
		if _is_rest_or_holiday(attendance_date, holiday_dates, shift_name, roster_work_days):
			continue

		shift = shift_map.get(shift_name)
		if not (shift and shift.start_time):
			continue

		total += _get_late_hours(
			attendance.in_time,
			shift.start_time,
			_get_late_grace_period_seconds(shift),
		)

	total += _calculate_checkin_late_hours(
		employee,
		start_date,
		end_date,
		dates_with_attendance,
		holiday_dates,
		shift_assignments,
		shift_map,
		employee_doc.default_shift,
		roster_work_days,
	)

	return round(total, 2)


def _calculate_checkin_late_hours(
	employee,
	start_date,
	end_date,
	dates_with_attendance,
	holiday_dates,
	shift_assignments,
	shift_map,
	default_shift,
	roster_work_days=None,
):
	checkins_by_date = {}
	for checkin in frappe.get_all(
		"Employee Checkin",
		filters={
			"employee": employee,
			"time": ["between", [f"{start_date} 00:00:00", f"{end_date} 23:59:59"]],
			"skip_auto_attendance": 0,
		},
		fields=["time", "log_type", "shift"],
		order_by="time asc",
		limit_page_length=50000,
	):
		checkin_date = str(getdate(checkin.time))
		if checkin_date in dates_with_attendance:
			continue
		if checkin.log_type and checkin.log_type != "IN":
			continue
		checkins_by_date.setdefault(checkin_date, checkin)

	total = 0.0
	for checkin_date, checkin in checkins_by_date.items():
		shift_name = shift_assignments.get(checkin_date) or checkin.shift or default_shift
		if _is_rest_or_holiday(checkin_date, holiday_dates, shift_name, roster_work_days):
			continue
		shift = shift_map.get(shift_name)
		if not (shift and shift.start_time):
			continue

		total += _get_late_hours(
			checkin.time,
			shift.start_time,
			_get_late_grace_period_seconds(shift),
		)
	return total


def _get_holiday_dates(holiday_list, start_date, end_date):
	if not holiday_list:
		return set()

	return {
		str(row.holiday_date)
		for row in frappe.get_all(
			"Holiday",
			filters={"parent": holiday_list, "holiday_date": ["between", [start_date, end_date]]},
			fields=["holiday_date"],
		)
	}


def _get_shift_assignments(employee, start_date, end_date):
	assignments = {}
	rows = frappe.get_all(
		"Shift Assignment",
		filters={
			"employee": employee,
			"docstatus": 1,
			"start_date": ["<=", end_date],
		},
		fields=["shift_type", "start_date", "end_date"],
		order_by="start_date asc",
	)
	for row in rows:
		row_start = str(getdate(row.start_date))
		row_end = str(getdate(row.end_date)) if row.end_date else end_date
		current = max(row_start, start_date)
		last = min(row_end, end_date)
		if current > last:
			continue
		for index in range(frappe.utils.date_diff(last, current) + 1):
			assignments[str(add_days(current, index))] = row.shift_type
	return assignments


def _is_rest_or_holiday(attendance_date, holiday_dates, shift_name=None, work_days=None):
	return is_rest_day_from_work_days(attendance_date, work_days, shift_name) or attendance_date in holiday_dates


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


def _get_basic_pay_amount(salary_slip):
	for row in salary_slip.get("earnings", []):
		if row.salary_component == "Basic Pay":
			return flt(row.amount)
	return 0.0


def get_salary_slip_daily_rate(salary_slip):
	if is_weekly_employee(salary_slip):
		return get_employee_daily_rate(salary_slip.employee)

	basic_pay = _get_basic_pay_amount(salary_slip)
	if not basic_pay:
		return 0.0

	payment_days = flt(salary_slip.payment_days) or flt(salary_slip.working_days) or 1
	return basic_pay / payment_days if payment_days else 0.0


def is_weekly_employee(doc):
	if doc.payroll_frequency == "Weekly":
		return True

	if not doc.employee:
		return False

	return (
		frappe.db.get_value("Employee", doc.employee, "custom_payroll_type") or ""
	) == "Weekly"


def get_employee_daily_rate(employee):
	if not employee:
		return 0.0

	return flt(frappe.db.get_value("Employee", employee, "custom_mwe_rate_per_day"))


def _get_salary_component_data(salary_component):
	return (
		frappe.db.get_value(
			"Salary Component",
			salary_component,
			[
				"salary_component_abbr",
				"depends_on_payment_days",
				"do_not_include_in_total",
				"do_not_include_in_accounts",
				"is_tax_applicable",
				"is_flexible_benefit",
				"variable_based_on_taxable_salary",
				"exempted_from_income_tax",
			],
			as_dict=True,
		)
		or {}
	)


def set_salary_component_amount(salary_slip, table_field, salary_component, amount):
	amount = flt(amount, 2)
	table = list(salary_slip.get(table_field) or [])
	existing_row = None

	for row in table:
		if row.salary_component != salary_component:
			continue
		if row.get("additional_salary"):
			continue
		existing_row = row
		break

	if amount <= 0:
		salary_slip.set(
			table_field,
			[
				row
				for row in table
				if not (row.salary_component == salary_component and not row.get("additional_salary"))
			],
		)
		_recalculate_salary_slip_totals(salary_slip)
		return

	component = _get_salary_component_data(salary_component)
	values = {
		"salary_component": salary_component,
		"abbr": component.get("salary_component_abbr"),
		"depends_on_payment_days": component.get("depends_on_payment_days") or 0,
		"do_not_include_in_total": component.get("do_not_include_in_total") or 0,
		"do_not_include_in_accounts": component.get("do_not_include_in_accounts") or 0,
		"is_tax_applicable": component.get("is_tax_applicable") or 0,
		"is_flexible_benefit": component.get("is_flexible_benefit") or 0,
		"variable_based_on_taxable_salary": component.get("variable_based_on_taxable_salary") or 0,
		"exempted_from_income_tax": component.get("exempted_from_income_tax") or 0,
		"default_amount": amount,
		"additional_amount": 0,
		"amount": amount,
	}

	if existing_row:
		for key, value in values.items():
			existing_row.set(key, value)
	else:
		salary_slip.append(table_field, values)

	_recalculate_salary_slip_totals(salary_slip)


def _recalculate_salary_slip_totals(salary_slip):
	if hasattr(salary_slip, "set_precision_for_component_amounts"):
		salary_slip.set_precision_for_component_amounts()
	if hasattr(salary_slip, "get_component_totals"):
		salary_slip.gross_pay = salary_slip.get_component_totals(
			"earnings",
			depends_on_payment_days=1,
		)
		salary_slip.total_deduction = salary_slip.get_component_totals(
			"deductions",
			depends_on_payment_days=1,
		)
		salary_slip.base_gross_pay = flt(
			flt(salary_slip.gross_pay) * flt(salary_slip.exchange_rate or 1),
			salary_slip.precision("base_gross_pay"),
		)
		salary_slip.base_total_deduction = flt(
			flt(salary_slip.total_deduction) * flt(salary_slip.exchange_rate or 1),
			salary_slip.precision("base_total_deduction"),
		)
	if hasattr(salary_slip, "set_net_pay"):
		salary_slip.set_net_pay()


def _get_shift_map():
	return {
		shift.name: shift
		for shift in frappe.get_all(
			"Shift Type",
			fields=["name", "start_time", "end_time"],
		)
	}


def _get_checkin_pairs_by_date(employee, start_date, end_date):
	checkins_by_date = {}
	for checkin in frappe.get_all(
		"Employee Checkin",
		filters={
			"employee": employee,
			"time": ["between", [f"{start_date} 00:00:00", f"{end_date} 23:59:59"]],
			"skip_auto_attendance": 0,
		},
		fields=["time", "log_type", "shift"],
		order_by="time asc",
		limit_page_length=50000,
	):
		checkin_date = str(getdate(checkin.time))
		pair = checkins_by_date.setdefault(
			checkin_date,
			{"in_time": None, "out_time": None, "shift": checkin.shift},
		)
		if checkin.shift and not pair.get("shift"):
			pair["shift"] = checkin.shift
		if checkin.log_type == "IN" and not pair.get("in_time"):
			pair["in_time"] = checkin.time
		elif checkin.log_type == "OUT":
			pair["out_time"] = checkin.time
		elif not checkin.log_type:
			if not pair.get("in_time"):
				pair["in_time"] = checkin.time
			else:
				pair["out_time"] = checkin.time
	return checkins_by_date


def _get_shift_hours(shift):
	if not (shift and shift.start_time and shift.end_time):
		return 8.0

	start_seconds = shift.start_time.seconds
	end_seconds = shift.end_time.seconds
	if end_seconds <= start_seconds:
		end_seconds += 24 * 60 * 60

	hours = (end_seconds - start_seconds) / 3600
	return flt(hours, 2) or 8.0


def _get_night_differential_hours(time_in, time_out):
	if not (time_in and time_out):
		return 0.0

	start = _as_datetime(time_in)
	end = _as_datetime(time_out)
	if not (start and end):
		return 0.0
	if end <= start:
		end += timedelta(days=1)

	total_seconds = 0
	current_date = start.date() - timedelta(days=1)
	last_date = end.date()
	while current_date <= last_date:
		night_start = datetime.combine(current_date, time(NIGHT_DIFFERENTIAL_START_HOUR, 0))
		night_end = datetime.combine(
			current_date + timedelta(days=1),
			time(NIGHT_DIFFERENTIAL_END_HOUR, 0),
		)
		overlap_start = max(start, night_start)
		overlap_end = min(end, night_end)
		if overlap_end > overlap_start:
			total_seconds += (overlap_end - overlap_start).total_seconds()
		current_date += timedelta(days=1)

	return flt(total_seconds / 3600, 2)


def _as_datetime(value):
	if isinstance(value, datetime):
		return value
	if isinstance(value, str):
		return frappe.utils.get_datetime(value)
	return None
