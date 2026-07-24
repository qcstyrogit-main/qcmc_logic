from datetime import datetime, timedelta

import frappe
from frappe.utils import flt, getdate


SAMPLE_EMPLOYEE = "HR-EMP-00337"


def _dt(date_value, time_value):
	return f"{date_value} {time_value}:00"


def _hours(start_dt, end_dt):
	start = datetime.strptime(start_dt, "%Y-%m-%d %H:%M:%S")
	end = datetime.strptime(end_dt, "%Y-%m-%d %H:%M:%S")
	if end < start:
		end += timedelta(days=1)
	return round((end - start).total_seconds() / 3600, 2)


def _shift_for_date(date_value):
	day_name = getdate(date_value).strftime("%A")
	if day_name == "Monday":
		return "Monday Shift - QC", "07:30", "18:00"
	if day_name in ("Tuesday", "Wednesday", "Thursday", "Friday"):
		return "Tue-Fri Shift - QC", "07:30", "17:30"
	return None, None, None


def _get_sample_rows():
	absent_dates = {"2026-03-10", "2026-03-24", "2026-04-07", "2026-04-21"}
	custom_times = {
		"2026-03-02": ("07:28", "17:31"),
		"2026-03-03": ("07:32", "19:30"),
		"2026-03-04": ("07:29", "17:29"),
		"2026-03-05": ("07:44", "17:35"),
		"2026-03-06": ("07:27", "20:03"),
		"2026-03-09": ("07:56", "18:05"),
		"2026-03-11": ("07:33", "17:31"),
		"2026-03-12": ("07:30", "18:45"),
		"2026-03-13": ("07:29", "19:59"),
		"2026-03-14": ("08:00", "15:30"),
		"2026-03-16": ("07:51", "18:03"),
		"2026-03-17": ("07:28", "17:32"),
		"2026-03-18": ("07:30", "19:05"),
		"2026-03-19": ("07:29", "17:28"),
		"2026-03-20": ("07:32", "20:00"),
		"2026-03-23": ("07:47", "18:00"),
		"2026-03-25": ("07:30", "17:29"),
		"2026-03-26": ("07:31", "18:40"),
		"2026-03-27": ("07:28", "19:31"),
		"2026-03-30": ("07:54", "18:02"),
		"2026-03-31": ("07:29", "17:31"),
		"2026-04-01": ("07:28", "17:32"),
		"2026-04-02": ("07:35", "20:35"),
		"2026-04-03": ("07:32", "19:32"),
		"2026-04-04": ("08:00", "13:00"),
		"2026-04-06": ("07:52", "19:03"),
		"2026-04-08": ("08:04", "17:40"),
		"2026-04-09": ("07:30", "20:31"),
		"2026-04-10": ("07:29", "17:34"),
		"2026-04-13": ("07:49", "18:01"),
		"2026-04-14": ("07:28", "20:28"),
		"2026-04-15": ("07:30", "18:31"),
		"2026-04-16": ("07:28", "17:28"),
		"2026-04-17": ("07:29", "17:33"),
		"2026-04-20": ("07:57", "18:02"),
		"2026-04-22": ("07:28", "19:58"),
		"2026-04-23": ("07:29", "17:31"),
		"2026-04-24": ("07:31", "17:30"),
		"2026-04-27": ("07:50", "18:03"),
		"2026-04-28": ("07:29", "19:30"),
		"2026-04-29": ("07:34", "19:04"),
		"2026-04-30": ("07:28", "17:32"),
	}
	overtime = {
		"2026-03-03": ("Regular OT", 2),
		"2026-03-06": ("Regular OT", 2.5),
		"2026-03-13": ("Regular OT", 2),
		"2026-03-14": ("Rest Day OT", 3),
		"2026-03-20": ("Regular OT", 2),
		"2026-03-27": ("Regular OT", 2),
		"2026-04-02": ("Regular Holiday OT", 3),
		"2026-04-03": ("Regular Holiday OT", 2),
		"2026-04-04": ("Special Holiday Rest Day OT", 2),
		"2026-04-09": ("Regular Holiday OT", 3),
		"2026-04-14": ("Regular OT", 3),
		"2026-04-15": ("Regular OT", 1),
		"2026-04-22": ("Regular OT", 2.5),
		"2026-04-28": ("Regular OT", 2),
		"2026-04-29": ("Regular OT", 1.5),
	}

	rows = []
	date_value = getdate("2026-03-01")
	end_date = getdate("2026-04-30")
	while date_value <= end_date:
		date_key = str(date_value)
		shift, scheduled_start, scheduled_end = _shift_for_date(date_key)
		if date_key in absent_dates:
			rows.append(
				{
					"date": date_key,
					"status": "Absent",
					"shift": shift,
					"in_time": None,
					"out_time": None,
					"late_entry": 0,
					"overtime_type": None,
					"actual_overtime_duration": 0,
				}
			)
		elif date_key in custom_times:
			in_time, out_time = custom_times[date_key]
			in_datetime = _dt(date_key, in_time)
			out_datetime = _dt(date_key, out_time)
			ot_type, ot_duration = overtime.get(date_key, (None, 0))
			rows.append(
				{
					"date": date_key,
					"status": "Present",
					"shift": shift,
					"in_time": in_datetime,
					"out_time": out_datetime,
					"late_entry": 1 if scheduled_start and in_time > scheduled_start else 0,
					"overtime_type": ot_type,
					"actual_overtime_duration": ot_duration,
				}
			)
		date_value += timedelta(days=1)

	return rows


@frappe.whitelist()
def create_aaron_march_april_sample():
	return create_sample_attendance(SAMPLE_EMPLOYEE, "2026-03-01", "2026-04-30")


@frappe.whitelist()
def create_joselito_march_april_sample():
	return create_sample_attendance("HR-EMP-00581", "2026-03-01", "2026-04-30")


@frappe.whitelist()
def create_remy_february_july_sample():
	"""Create the approved 6 AM-8 PM payroll test data, with Saturday as rest day."""
	employee = "HR-EMP-00618"
	shift = "66 - 6 to 6 (DaytoNight-RD-Sat)"
	from_date = getdate("2026-02-01")
	to_date = getdate("2026-07-15")
	employee_doc = frappe.get_doc("Employee", employee)

	created_attendance = 0
	created_checkins = 0
	skipped_existing = 0
	skipped_rest_days = 0
	date_value = from_date

	while date_value <= to_date:
		date_key = str(date_value)
		if date_value.strftime("%A") == "Saturday":
			skipped_rest_days += 1
			date_value += timedelta(days=1)
			continue

		if frappe.db.exists(
			"Attendance",
			{"employee": employee, "attendance_date": date_key, "docstatus": ["!=", 2]},
		):
			skipped_existing += 1
			date_value += timedelta(days=1)
			continue

		row = {
			"date": date_key,
			"status": "Present",
			"shift": shift,
			"in_time": _dt(date_key, "06:00"),
			"out_time": _dt(date_key, "20:00"),
			"late_entry": 0,
			"overtime_type": "Regular OT",
			"actual_overtime_duration": 6,
		}
		attendance = _upsert_attendance(employee_doc, row)
		created_attendance += 1
		created_checkins += _sync_checkins(employee_doc, attendance, row)
		date_value += timedelta(days=1)

	frappe.db.commit()
	return {
		"employee": employee,
		"from_date": str(from_date),
		"to_date": str(to_date),
		"created_attendance": created_attendance,
		"created_checkins": created_checkins,
		"skipped_existing": skipped_existing,
		"skipped_rest_days": skipped_rest_days,
	}


@frappe.whitelist()
def set_remy_july_8_14_mixed_overtime():
	"""Make the second July test week show default-only and beyond-shift OT days."""
	default_only_dates = {"2026-07-08", "2026-07-10", "2026-07-12", "2026-07-14"}
	updated = []

	for date_key in sorted(default_only_dates):
		attendance_name = frappe.db.get_value(
			"Attendance",
			{
				"employee": "HR-EMP-00618",
				"attendance_date": date_key,
				"docstatus": 1,
			},
			"name",
		)
		if not attendance_name:
			continue

		out_time = _dt(date_key, "18:00")
		frappe.db.set_value(
			"Attendance",
			attendance_name,
			{
				"out_time": out_time,
				"working_hours": 12,
				"actual_overtime_duration": 4,
			},
			update_modified=False,
		)
		out_checkin = frappe.db.get_value(
			"Employee Checkin",
			{"attendance": attendance_name, "log_type": "OUT"},
			"name",
		)
		if out_checkin:
			frappe.db.set_value(
				"Employee Checkin",
				out_checkin,
				"time",
				out_time,
				update_modified=False,
			)
		updated.append(date_key)

	frappe.db.commit()
	return {"updated_default_only_dates": updated}


@frappe.whitelist()
def fix_payroll_entry_00013_payable_account():
	frappe.db.set_value(
		"Salary Structure Assignment",
		"HR-SSA-26-07-00003",
		"payroll_payable_account",
		"2120 - Payroll Payable - QC",
	)
	doc = frappe.get_doc("Payroll Entry", "HR-PRUN-2026-00013")
	doc.payroll_payable_account = "2120 - Payroll Payable - QC"
	doc.fill_employee_details()
	doc.save(ignore_permissions=True)
	frappe.db.commit()
	return {
		"payroll_entry": doc.name,
		"payroll_payable_account": doc.payroll_payable_account,
		"number_of_employees": doc.number_of_employees,
		"employees": [row.employee for row in doc.employees],
	}


@frappe.whitelist()
def delete_recent_sample_salary_slips():
	return delete_all_payroll_entries()


@frappe.whitelist()
def delete_recent_sample_payroll_entries():
	return delete_all_payroll_entries()


@frappe.whitelist()
def delete_all_payroll_entries():
	payroll_entries = frappe.get_all("Payroll Entry", pluck="name")
	deleted = []

	if not payroll_entries:
		return [{"status": "No Payroll Entries found"}]

	salary_slips = frappe.get_all(
		"Salary Slip",
		filters={"payroll_entry": ["in", payroll_entries]},
		pluck="name",
	)

	loan_repayments = []
	if salary_slips:
		loan_repayments = frappe.get_all(
			"Salary Slip Loan",
			filters={
				"parent": ["in", salary_slips],
				"loan_repayment_entry": ["is", "set"],
			},
			pluck="loan_repayment_entry",
		)
		loan_repayments = sorted(set(loan_repayments))

	overtime_slips = frappe.get_all(
		"Overtime Slip",
		filters={"payroll_entry": ["in", payroll_entries]},
		pluck="name",
	)

	journal_entries = set(
		frappe.get_all(
			"GL Entry",
			filters={
				"against_voucher_type": "Payroll Entry",
				"against_voucher": ["in", payroll_entries],
			},
			pluck="voucher_no",
		)
	)

	additional_salaries = []
	if overtime_slips:
		additional_salaries = frappe.get_all(
			"Additional Salary",
			filters={
				"ref_doctype": "Overtime Slip",
				"ref_docname": ["in", overtime_slips],
			},
			pluck="name",
		)

	for doctype, names in [
		("Journal Entry", sorted(journal_entries)),
		("Salary Slip", salary_slips),
		("Loan Repayment", loan_repayments),
		("Additional Salary", additional_salaries),
		("Overtime Slip", overtime_slips),
		("Payroll Entry", payroll_entries),
	]:
		for name in names:
			if not frappe.db.exists(doctype, name):
				continue

			doc = frappe.get_doc(doctype, name)

			if doc.docstatus == 1:
				doc.cancel()

			frappe.delete_doc(
				doctype,
				name,
				ignore_permissions=True,
				force=True,
			)

			deleted.append({
				"name": name,
				"doctype": doctype,
				"status": "deleted",
			})

	frappe.db.commit()
	return deleted

@frappe.whitelist()
def create_sample_attendance(employee, from_date, to_date):
	employee_doc = frappe.get_doc("Employee", employee)
	rows = [
		row
		for row in _get_sample_rows()
		if str(getdate(from_date)) <= row["date"] <= str(getdate(to_date))
	]

	created_attendance = 0
	updated_attendance = 0
	created_checkins = 0

	for row in rows:
		attendance = _upsert_attendance(employee_doc, row)
		if attendance.flags.was_created:
			created_attendance += 1
		else:
			updated_attendance += 1

		if row["status"] == "Present":
			created_checkins += _sync_checkins(employee_doc, attendance, row)

	frappe.db.commit()
	return {
		"employee": employee,
		"created_attendance": created_attendance,
		"updated_attendance": updated_attendance,
		"created_checkins": created_checkins,
	}


def _upsert_attendance(employee_doc, row):
	existing = frappe.db.exists(
		"Attendance",
		{"employee": employee_doc.name, "attendance_date": row["date"], "docstatus": ["!=", 2]},
	)

	if existing:
		attendance = frappe.get_doc("Attendance", existing)
		if attendance.docstatus == 1:
			attendance.cancel()
			attendance = frappe.copy_doc(attendance)
			attendance.amended_from = existing
			attendance.docstatus = 0
	else:
		attendance = frappe.new_doc("Attendance")
		attendance.flags.was_created = True

	attendance.employee = employee_doc.name
	attendance.employee_name = employee_doc.employee_name
	attendance.company = employee_doc.company
	attendance.department = employee_doc.department
	attendance.attendance_date = row["date"]
	attendance.status = row["status"]
	attendance.shift = row["shift"]
	attendance.in_time = row["in_time"]
	attendance.out_time = row["out_time"]
	attendance.working_hours = _hours(row["in_time"], row["out_time"]) if row["in_time"] and row["out_time"] else 0
	attendance.standard_working_hours = 8
	attendance.late_entry = row["late_entry"]
	attendance.overtime_type = row["overtime_type"]
	attendance.actual_overtime_duration = flt(row["actual_overtime_duration"])
	attendance.flags.ignore_validate = True
	attendance.flags.ignore_mandatory = True
	attendance.flags.ignore_links = True
	attendance.save(ignore_permissions=True)
	attendance.submit()
	return attendance


def _sync_checkins(employee_doc, attendance, row):
	count = 0
	for log_type, time_value in (("IN", row["in_time"]), ("OUT", row["out_time"])):
		if not time_value:
			continue
		existing = frappe.db.exists(
			"Employee Checkin",
			{
				"employee": employee_doc.name,
				"time": time_value,
				"log_type": log_type,
			},
		)
		if existing:
			frappe.db.set_value(
				"Employee Checkin",
				existing,
				{"attendance": attendance.name, "shift": row["shift"]},
				update_modified=False,
			)
			continue

		checkin = frappe.new_doc("Employee Checkin")
		checkin.employee = employee_doc.name
		checkin.employee_name = employee_doc.employee_name
		checkin.time = time_value
		checkin.log_type = log_type
		checkin.shift = row["shift"]
		checkin.latitude = 0.000001
		checkin.longitude = 0.000001
		checkin.skip_auto_attendance = 1
		checkin.insert(ignore_permissions=True)
		frappe.db.set_value(
			"Employee Checkin",
			checkin.name,
			{"attendance": attendance.name},
			update_modified=False,
		)
		count += 1

	return count
