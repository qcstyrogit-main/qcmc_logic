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
	salary_slips = [
		"Sal Slip/HR-EMP-00554/00002",
		"Sal Slip/HR-EMP-00337/00001",
		"Sal Slip/HR-EMP-00554/00001",
	]
	deleted = []
	for name in salary_slips:
		if not frappe.db.exists("Salary Slip", name):
			deleted.append({"name": name, "status": "already missing"})
			continue

		doc = frappe.get_doc("Salary Slip", name)
		if doc.docstatus == 1:
			doc.cancel()
		frappe.delete_doc("Salary Slip", name, ignore_permissions=True, force=True)
		deleted.append({"name": name, "status": "deleted"})

	frappe.db.commit()
	return deleted


@frappe.whitelist()
def delete_recent_sample_payroll_entries():
	payroll_entries = ["HR-PRUN-2026-00013", "HR-PRUN-2026-00012"]
	deleted = []
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
	overtime_slips = frappe.get_all(
		"Overtime Slip",
		filters={"payroll_entry": ["in", payroll_entries]},
		pluck="name",
	)
	for journal_entry in sorted(journal_entries):
		if not frappe.db.exists("Journal Entry", journal_entry):
			continue

		doc = frappe.get_doc("Journal Entry", journal_entry)
		if doc.docstatus == 1:
			doc.cancel()
		frappe.delete_doc("Journal Entry", journal_entry, ignore_permissions=True, force=True)
		deleted.append({"name": journal_entry, "doctype": "Journal Entry", "status": "deleted"})

	for salary_slip in frappe.get_all(
		"Salary Slip",
		filters={"payroll_entry": ["in", payroll_entries]},
		pluck="name",
	):
		doc = frappe.get_doc("Salary Slip", salary_slip)
		if doc.docstatus == 1:
			doc.cancel()
		frappe.delete_doc("Salary Slip", salary_slip, ignore_permissions=True, force=True)
		deleted.append({"name": salary_slip, "doctype": "Salary Slip", "status": "deleted"})

	for additional_salary in frappe.get_all(
		"Additional Salary",
		filters={"ref_doctype": "Overtime Slip", "ref_docname": ["in", overtime_slips]},
		pluck="name",
	):
		doc = frappe.get_doc("Additional Salary", additional_salary)
		if doc.docstatus == 1:
			doc.cancel()
		frappe.delete_doc("Additional Salary", additional_salary, ignore_permissions=True, force=True)
		deleted.append({"name": additional_salary, "doctype": "Additional Salary", "status": "deleted"})

	for overtime_slip in overtime_slips:
		doc = frappe.get_doc("Overtime Slip", overtime_slip)
		if doc.docstatus == 1:
			doc.cancel()
		frappe.delete_doc("Overtime Slip", overtime_slip, ignore_permissions=True, force=True)
		deleted.append({"name": overtime_slip, "doctype": "Overtime Slip", "status": "deleted"})

	for name in payroll_entries:
		if not frappe.db.exists("Payroll Entry", name):
			deleted.append({"name": name, "doctype": "Payroll Entry", "status": "already missing"})
			continue

		doc = frappe.get_doc("Payroll Entry", name)
		if doc.docstatus == 1:
			doc.cancel()
		frappe.delete_doc("Payroll Entry", name, ignore_permissions=True, force=True)
		deleted.append({"name": name, "doctype": "Payroll Entry", "status": "deleted"})

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
