import frappe
from frappe import _
from frappe.utils import add_days, cint, flt, getdate, nowdate
from hrms.payroll.doctype.salary_structure_assignment.salary_structure_assignment import (
	get_assigned_salary_structure,
)

from qcmc_logic.api.employee_attendance_schedule import _get_logged_in_employee_filters
from qcmc_logic.customs.overtime_policy import normalize_overtime_duration
from qcmc_logic.customs.rest_day import get_employee_roster_work_days, is_rest_day_from_work_days


PARENT_DOCTYPE = "Batch Overtime Entry"
CHILD_DOCTYPE = "Batch Overtime Detail"
DEFAULT_REGULAR_OT_TYPE = "Regular OT"
DEFAULT_REST_DAY_OT_TYPE = "Rest Day OT"
DEFAULT_HOLIDAY_OT_TYPE = "Regular Holiday OT"


def _date(value):
	return str(getdate(value))


def _field(fieldname, label, fieldtype, **kwargs):
	field = {
		"fieldname": fieldname,
		"label": label,
		"fieldtype": fieldtype,
	}
	field.update(kwargs)
	return field


def _parent_fields():
	return [
		_field("naming_series", "Series", "Select", options="BOE-.YYYY.-.####", default="BOE-.YYYY.-.####"),
		_field("payroll_entry", "Payroll Entry", "Link", options="Payroll Entry", in_list_view=1, in_standard_filter=1, allow_on_submit=1),
		_field("company", "Company", "Link", options="Company", reqd=1, in_list_view=1, in_standard_filter=1),
		_field("from_date", "From Date", "Date", reqd=1, in_list_view=1),
		_field("to_date", "To Date", "Date", reqd=1, in_list_view=1),
		_field("column_break_filters", None, "Column Break"),
		_field("department", "Department", "Link", options="Department", in_standard_filter=1),
		_field("branch", "Branch", "Link", options="Branch", in_standard_filter=1),
		_field("employment_type", "Employment Type", "Select", options="\nRegular\nProbationary"),
		_field("custom_payroll_type", "Payroll Type", "Select", options="\nMonthly\nWeekly"),
		_field("summary_section", "Summary", "Section Break"),
		_field("status", "Status", "Select", options="Draft\nFetched\nCreated\nPartly Created", default="Draft", read_only=1, in_list_view=1),
		_field("total_employees", "Employees", "Int", read_only=1),
		_field("total_rows", "OT Rows", "Int", read_only=1),
		_field("created_slips", "Created Slips", "Int", read_only=1),
		_field("column_break_summary", None, "Column Break"),
		_field("total_overtime_duration", "Total OT", "Float", read_only=1),
		_field("skipped_rows", "Skipped Rows", "Int", read_only=1),
		_field("last_created_on", "Last Created On", "Datetime", read_only=1),
		_field("details_section", "Overtime Details", "Section Break"),
		_field("details", "Details", "Table", options=CHILD_DOCTYPE),
	]


def _child_fields():
	return [
		_field("selected", "Select", "Check", default="1", in_list_view=1, columns=1),
		_field("employee", "Employee", "Link", options="Employee", read_only=1, in_list_view=1, columns=2),
		_field("employee_name", "Employee Name", "Data", read_only=1, in_list_view=1, columns=2),
		_field("attendance", "Attendance", "Link", options="Attendance", read_only=1, in_list_view=1, columns=2),
		_field("date", "Date", "Date", read_only=1, in_list_view=1, columns=1),
		_field("overtime_type", "Overtime Type", "Link", options="Overtime Type", read_only=1, in_list_view=1, columns=2),
		_field("overtime_duration", "OT Duration", "Float", read_only=1, in_list_view=1, columns=1),
		_field("standard_working_hours", "Standard Hours", "Float", read_only=1),
		_field("column_break_meta", None, "Column Break"),
		_field("department", "Department", "Link", options="Department", read_only=1),
		_field("branch", "Branch", "Link", options="Branch", read_only=1),
		_field("created_overtime_slip", "Overtime Slip", "Link", options="Overtime Slip", read_only=1, in_list_view=1, columns=2),
		_field("row_status", "Status", "Data", read_only=1, in_list_view=1, columns=1),
		_field("error_message", "Error Message", "Small Text", read_only=1),
	]


def _permissions():
	return [
		{"role": "System Manager", "read": 1, "write": 1, "create": 1, "delete": 1, "submit": 1, "cancel": 1, "amend": 1, "export": 1, "print": 1, "email": 1, "share": 1},
		{"role": "HR Manager", "read": 1, "write": 1, "create": 1, "delete": 1, "submit": 1, "cancel": 1, "amend": 1, "export": 1, "print": 1, "email": 1, "share": 1},
		{"role": "HR User", "read": 1, "write": 1, "create": 1, "delete": 0, "submit": 0, "cancel": 0, "amend": 0, "export": 1, "print": 1, "email": 1, "share": 1},
	]


def _sync_doctype(name, fields, istable=0):
	if frappe.db.exists("DocType", name):
		doc = frappe.get_doc("DocType", name)
	else:
		doc = frappe.new_doc("DocType")
		doc.name = name

	doc.module = "QCMC Logics"
	doc.custom = 1
	doc.istable = istable
	doc.is_submittable = 0 if istable else 1
	doc.editable_grid = 1
	doc.allow_import = 1
	doc.track_changes = 1 if not istable else 0
	doc.autoname = "naming_series:" if not istable else None
	doc.title_field = "company" if not istable else None
	doc.sort_field = "modified"
	doc.sort_order = "DESC"
	doc.grid_page_length = 50
	doc.rows_threshold_for_grid_search = 20
	doc.set("fields", [])
	for field in fields:
		doc.append("fields", field)
	doc.set("permissions", [] if istable else _permissions())

	if doc.is_new():
		doc.insert(ignore_permissions=True)
	else:
		doc.save(ignore_permissions=True)

	frappe.clear_cache(doctype=name)
	return doc.name


@frappe.whitelist()
def install_batch_overtime_doctypes():
	_sync_doctype(CHILD_DOCTYPE, _child_fields(), istable=1)
	_sync_doctype(PARENT_DOCTYPE, _parent_fields(), istable=0)
	frappe.db.commit()
	return {"created": [PARENT_DOCTYPE, CHILD_DOCTYPE]}


@frappe.whitelist()
def install_batch_overtime_client_script():
	return _install_client_script(
		"Batch Overtime Entry-Form",
		PARENT_DOCTYPE,
		frappe.get_app_path("qcmc_logic", "public", "js", "batch_overtime_entry.js"),
	)


@frappe.whitelist()
def install_payroll_entry_client_script():
	return _install_client_script(
		"Payroll Entry-Batch Overtime",
		"Payroll Entry",
		frappe.get_app_path("qcmc_logic", "public", "js", "payroll_entry.js"),
	)


def _install_client_script(name, doctype, script_path):
	if frappe.db.exists("Client Script", name):
		client_script = frappe.get_doc("Client Script", name)
	else:
		client_script = frappe.new_doc("Client Script")
		client_script.name = name

	with open(script_path) as script_file:
		script = script_file.read()

	client_script.dt = doctype
	client_script.view = "Form"
	client_script.enabled = 1
	client_script.script = script
	client_script.save(ignore_permissions=True)
	frappe.clear_cache(doctype=doctype)
	frappe.db.commit()
	return client_script.name


def _employee_filters(company, department=None, branch=None, employment_type=None, custom_payroll_type=None):
	filters = {"status": "Active"}
	filters.update(_get_logged_in_employee_filters(company))
	if department:
		filters["department"] = department
	if branch:
		filters["branch"] = branch
	if employment_type:
		filters["employment_type"] = employment_type
	if custom_payroll_type:
		filters["custom_payroll_type"] = custom_payroll_type
	return filters


def _fmt_date_key(employee, date_value):
	return (employee, str(getdate(date_value)))


def _get_existing_overtime_dates(employee_names, from_date, to_date):
	if not employee_names:
		return set()

	details = frappe.get_all(
		"Overtime Details",
		filters={"date": ["between", [from_date, to_date]]},
		fields=["parent", "date"],
	)
	parents = list({detail.parent for detail in details if detail.parent})
	if not parents:
		return set()

	active_slips = frappe.get_all(
		"Overtime Slip",
		filters={"name": ["in", parents], "employee": ["in", employee_names], "docstatus": ["!=", 2]},
		fields=["name", "employee"],
	)
	employee_by_slip = {slip.name: slip.employee for slip in active_slips}
	return {
		(employee_by_slip[detail.parent], str(detail.date))
		for detail in details
		if detail.parent in employee_by_slip
	}


def _get_shift_assignment_map(employee_names, from_date, to_date):
	shift_assignment_map = {}
	if not employee_names:
		return shift_assignment_map

	for assignment in frappe.get_all(
		"Shift Assignment",
		filters=[
			["employee", "in", employee_names],
			["docstatus", "=", 1],
			["start_date", "<=", to_date],
		],
		or_filters=[
			["end_date", ">=", from_date],
			["end_date", "is", "not set"],
		],
		fields=["employee", "shift_type", "start_date", "end_date"],
		order_by="start_date asc",
		limit_page_length=50000,
	):
		start_date = max(str(assignment.start_date), from_date)
		end_date = min(str(assignment.end_date or to_date), to_date)
		for index in range(frappe.utils.date_diff(end_date, start_date) + 1):
			shift_assignment_map[(assignment.employee, str(add_days(start_date, index)))] = assignment.shift_type

	return shift_assignment_map


def _get_holiday_dates_by_employee(employees, from_date, to_date):
	company_holiday_lists = {}
	holiday_dates_by_list = {}
	holiday_dates_by_employee = {}
	for employee in employees:
		if employee.company not in company_holiday_lists:
			company_holiday_lists[employee.company] = frappe.db.get_value(
				"Company", employee.company, "default_holiday_list"
			)
		holiday_list = getattr(employee, "holiday_list", None) or company_holiday_lists.get(employee.company)
		if holiday_list and holiday_list not in holiday_dates_by_list:
			holiday_dates_by_list[holiday_list] = {
				str(holiday.holiday_date)
				for holiday in frappe.get_all(
					"Holiday",
					filters={"parent": holiday_list, "holiday_date": ["between", [from_date, to_date]]},
					fields=["holiday_date"],
				)
			}
		holiday_dates_by_employee[employee.name] = holiday_dates_by_list.get(holiday_list, set())
	return holiday_dates_by_employee


def _get_checkin_map(employee_names, from_date, to_date):
	checkin_map = {}
	if not employee_names:
		return checkin_map

	for checkin in frappe.get_all(
		"Employee Checkin",
		filters={
			"employee": ["in", employee_names],
			"time": ["between", [f"{from_date} 00:00:00", f"{to_date} 23:59:59"]],
			"skip_auto_attendance": 0,
		},
		fields=["employee", "time", "log_type", "shift"],
		order_by="time asc",
		limit_page_length=50000,
	):
		checkin_date = str(getdate(checkin.time))
		row = checkin_map.setdefault(
			(checkin.employee, checkin_date),
			{"in_time": None, "out_time": None, "shift": None},
		)
		if checkin.shift and not row["shift"]:
			row["shift"] = checkin.shift
		if checkin.log_type == "IN":
			if not row["in_time"] or checkin.time < row["in_time"]:
				row["in_time"] = checkin.time
		elif checkin.log_type == "OUT":
			if not row["out_time"] or checkin.time > row["out_time"]:
				row["out_time"] = checkin.time
	return checkin_map


def _get_shift_hours(shift):
	if not (shift and shift.start_time and shift.end_time):
		return 8
	start_seconds = shift.start_time.seconds
	end_seconds = shift.end_time.seconds
	if end_seconds <= start_seconds:
		end_seconds += 24 * 3600
	return round((end_seconds - start_seconds) / 3600, 2)


def _get_duration_after_shift_end(out_time, shift):
	if not (out_time and shift and shift.end_time):
		return 0
	out_seconds = out_time.hour * 3600 + out_time.minute * 60
	end_seconds = shift.end_time.seconds
	if out_seconds < end_seconds and end_seconds - out_seconds > 12 * 3600:
		out_seconds += 24 * 3600
	duration = (out_seconds - end_seconds) / 3600
	return round(duration, 2) if duration > 0 else 0


def _get_overtime_type(sched_date, holiday_dates, shift_name=None, work_days=None):
	is_holiday = sched_date in holiday_dates
	if is_holiday and frappe.db.exists("Overtime Type", DEFAULT_HOLIDAY_OT_TYPE):
		return DEFAULT_HOLIDAY_OT_TYPE
	if is_rest_day_from_work_days(sched_date, work_days, shift_name) and frappe.db.exists(
		"Overtime Type", DEFAULT_REST_DAY_OT_TYPE
	):
		return DEFAULT_REST_DAY_OT_TYPE
	return DEFAULT_REGULAR_OT_TYPE if frappe.db.exists("Overtime Type", DEFAULT_REGULAR_OT_TYPE) else None


def _get_checkin_overtime_rows(employees, employee_map, from_date, to_date):
	employee_names = [employee.name for employee in employees]
	existing_dates = _get_existing_overtime_dates(employee_names, from_date, to_date)
	shift_assignment_map = _get_shift_assignment_map(employee_names, from_date, to_date)
	checkin_map = _get_checkin_map(employee_names, from_date, to_date)
	holiday_dates_by_employee = _get_holiday_dates_by_employee(employees, from_date, to_date)
	roster_work_days_by_employee = {
		employee.name: get_employee_roster_work_days(employee.name, from_date, to_date)
		for employee in employees
	}
	shift_map = {
		shift.name: shift
		for shift in frappe.get_all("Shift Type", fields=["name", "start_time", "end_time"])
	}

	rows = []
	for (employee, sched_date), checkin in sorted(checkin_map.items()):
		if (employee, sched_date) in existing_dates:
			continue
		shift_name = shift_assignment_map.get((employee, sched_date)) or checkin.get("shift")
		shift = shift_map.get(shift_name)
		if not shift:
			continue

		duration = _get_duration_after_shift_end(checkin.get("out_time"), shift)
		overtime_type = _get_overtime_type(
			sched_date,
			holiday_dates_by_employee.get(employee, set()),
			shift_name,
			roster_work_days_by_employee.get(employee),
		)
		duration = normalize_overtime_duration(duration, overtime_type)
		if duration <= 0:
			continue

		if not overtime_type:
			continue

		employee_doc = employee_map.get(employee)
		rows.append(
			{
				"selected": 1,
				"employee": employee,
				"employee_name": employee_doc.employee_name if employee_doc else "",
				"department": employee_doc.department if employee_doc else "",
				"branch": employee_doc.branch if employee_doc else "",
				"attendance": "",
				"date": sched_date,
				"overtime_type": overtime_type,
				"overtime_duration": duration,
				"standard_working_hours": _get_shift_hours(shift),
				"row_status": "Ready",
			}
		)
	return rows


def _existing_overtime_attendance(attendance_names):
	if not attendance_names:
		return set()

	details = frappe.get_all(
		"Overtime Details",
		filters={"reference_document": ["in", attendance_names]},
		fields=["parent", "reference_document"],
	)
	parents = list({detail.parent for detail in details if detail.parent})
	if not parents:
		return set()

	active_parents = {
		slip.name
		for slip in frappe.get_all(
			"Overtime Slip",
			filters={"name": ["in", parents], "docstatus": ["!=", 2]},
			fields=["name"],
		)
	}
	return {detail.reference_document for detail in details if detail.parent in active_parents}


@frappe.whitelist()
def sync_overtime_slip_payroll_entry(batch_name):
	doc = frappe.get_doc(PARENT_DOCTYPE, batch_name)
	if not doc.payroll_entry:
		frappe.throw(_("Please set Payroll Entry first."))
	if not frappe.get_meta("Overtime Slip").has_field("payroll_entry"):
		frappe.throw(_("Overtime Slip has no Payroll Entry field."))

	slip_names = sorted({row.created_overtime_slip for row in doc.details if row.created_overtime_slip})
	if not slip_names:
		frappe.throw(_("No created Overtime Slips found in this Batch Overtime Entry."))

	updated = 0
	for slip_name in slip_names:
		if not frappe.db.exists("Overtime Slip", {"name": slip_name, "docstatus": ["!=", 2]}):
			continue
		current = frappe.db.get_value("Overtime Slip", slip_name, "payroll_entry")
		if current == doc.payroll_entry:
			continue
		frappe.db.set_value("Overtime Slip", slip_name, "payroll_entry", doc.payroll_entry)
		updated += 1

	frappe.db.commit()
	return {"updated": updated, "total": len(slip_names)}


@frappe.whitelist()
def fetch_overtime_entries(company, from_date, to_date, department=None, branch=None, employment_type=None, custom_payroll_type=None):
	if not company:
		frappe.throw(_("Please select a Company."))
	if not from_date or not to_date:
		frappe.throw(_("Please set From Date and To Date."))

	from_date = _date(from_date)
	to_date = _date(to_date)
	if from_date > to_date:
		frappe.throw(_("From Date cannot be after To Date."))

	employees = frappe.get_all(
		"Employee",
		filters=_employee_filters(company, department, branch, employment_type, custom_payroll_type),
		fields=["name", "employee_name", "department", "branch", "company", "holiday_list"],
		order_by="employee_name asc",
	)
	employee_map = {employee.name: employee for employee in employees}
	if not employee_map:
		return {
			"rows": [],
			"total_employees": 0,
			"total_rows": 0,
			"total_overtime_duration": 0,
			"candidate_employees": 0,
			"submitted_attendance": 0,
			"ot_marked_attendance": 0,
			"already_used_attendance": 0,
		}

	submitted_attendance = frappe.db.count(
		"Attendance",
		{
			"employee": ["in", list(employee_map.keys())],
			"attendance_date": ["between", [from_date, to_date]],
			"docstatus": 1,
		},
	)

	attendance = frappe.get_all(
		"Attendance",
		filters={
			"employee": ["in", list(employee_map.keys())],
			"attendance_date": ["between", [from_date, to_date]],
			"docstatus": 1,
			"overtime_type": ["!=", ""],
			"actual_overtime_duration": [">", 0],
		},
		fields=[
			"name",
			"employee",
			"attendance_date",
			"shift",
			"overtime_type",
			"actual_overtime_duration",
			"standard_working_hours",
		],
		order_by="employee asc, attendance_date asc",
		limit_page_length=50000,
	)
	existing_attendance = _existing_overtime_attendance([row.name for row in attendance])
	holiday_dates_by_employee = _get_holiday_dates_by_employee(employees, from_date, to_date)
	shift_assignment_map = _get_shift_assignment_map(list(employee_map.keys()), from_date, to_date)
	roster_work_days_by_employee = {
		employee.name: get_employee_roster_work_days(employee.name, from_date, to_date)
		for employee in employees
	}
	rows = []
	total = 0.0
	overtime_type_cache = {}
	for row in attendance:
		if row.name in existing_attendance:
			continue
		employee = employee_map.get(row.employee)
		shift_name = row.shift or shift_assignment_map.get((row.employee, str(row.attendance_date)))
		overtime_type = (
			_get_overtime_type(
				str(row.attendance_date),
				holiday_dates_by_employee.get(row.employee, set()),
				shift_name,
				roster_work_days_by_employee.get(row.employee),
			)
			or row.overtime_type
		)
		duration = normalize_overtime_duration(
			row.actual_overtime_duration,
			overtime_type,
			overtime_type_cache,
		)
		if duration <= 0:
			continue
		total += duration
		rows.append(
			{
				"selected": 1,
				"employee": row.employee,
				"employee_name": employee.employee_name if employee else "",
				"department": employee.department if employee else "",
				"branch": employee.branch if employee else "",
				"attendance": row.name,
				"date": str(row.attendance_date),
				"overtime_type": overtime_type,
				"overtime_duration": duration,
				"standard_working_hours": flt(row.standard_working_hours) or 8,
				"row_status": "Ready",
			}
		)

	if not rows:
		checkin_rows = _get_checkin_overtime_rows(employees, employee_map, from_date, to_date)
		for row in checkin_rows:
			total += flt(row["overtime_duration"])
		rows.extend(checkin_rows)

	return {
		"rows": rows,
		"total_employees": len({row["employee"] for row in rows}),
		"total_rows": len(rows),
		"total_overtime_duration": total,
		"candidate_employees": len(employee_map),
		"submitted_attendance": submitted_attendance,
		"ot_marked_attendance": len(attendance),
		"already_used_attendance": len(existing_attendance),
	}


def _selected_rows(doc):
	return [
		row
		for row in doc.details
		if row.selected and row.date and flt(row.overtime_duration) > 0 and not row.created_overtime_slip
	]


def _validate_salary_structure_assignments(doc, rows):
	employees = sorted({row.employee for row in rows if row.employee})
	missing = []
	for employee in employees:
		salary_structure = get_assigned_salary_structure(employee, doc.from_date)
		if salary_structure:
			continue

		employee_name = frappe.db.get_value("Employee", employee, "employee_name") or employee
		missing.append(f"{employee} - {employee_name}")

	if missing:
		frappe.throw(
			_("Cannot submit Overtime Slips because these employees have no active Salary Structure Assignment on {0}:<br><br>{1}").format(
				frappe.bold(doc.from_date),
				"<br>".join(frappe.bold(employee) for employee in missing),
			)
		)


@frappe.whitelist()
def create_overtime_slips(batch_name):
	doc = frappe.get_doc(PARENT_DOCTYPE, batch_name)
	if not doc.company or not doc.from_date or not doc.to_date:
		frappe.throw(_("Company, From Date, and To Date are required."))

	rows = _selected_rows(doc)
	if not rows:
		frappe.throw(_("No selected overtime rows are ready to create."))

	attendance_rows = [row.attendance for row in rows if row.attendance]
	existing_attendance = _existing_overtime_attendance(attendance_rows)
	existing_dates = _get_existing_overtime_dates(sorted({row.employee for row in rows if row.employee}), doc.from_date, doc.to_date)
	grouped = {}
	for row in rows:
		if row.attendance and row.attendance in existing_attendance:
			row.row_status = "Skipped"
			row.error_message = "Attendance already has an active Overtime Slip."
			continue
		if not row.attendance and _fmt_date_key(row.employee, row.date) in existing_dates:
			row.row_status = "Skipped"
			row.error_message = "Employee/date already has an active Overtime Slip."
			continue
		grouped.setdefault(row.employee, []).append(row)

	_validate_salary_structure_assignments(doc, [row for group in grouped.values() for row in group])

	created = []
	for employee, employee_rows in grouped.items():
		employee_doc = frappe.db.get_value(
			"Employee",
			employee,
			["employee_name", "company", "department"],
			as_dict=True,
		)
		slip = frappe.new_doc("Overtime Slip")
		slip.posting_date = nowdate()
		slip.employee = employee
		slip.employee_name = employee_doc.employee_name if employee_doc else employee_rows[0].employee_name
		slip.company = employee_doc.company if employee_doc and employee_doc.company else doc.company
		slip.department = employee_doc.department if employee_doc else employee_rows[0].department
		slip.start_date = doc.from_date
		slip.end_date = doc.to_date
		if doc.payroll_entry and frappe.get_meta("Overtime Slip").has_field("payroll_entry"):
			slip.payroll_entry = doc.payroll_entry
		total = 0.0
		for row in employee_rows:
			duration = normalize_overtime_duration(row.overtime_duration, row.overtime_type)
			if duration <= 0:
				row.row_status = "Skipped"
				row.error_message = "OT duration is below the 1 hour minimum."
				continue
			total += duration
			slip.append(
				"overtime_details",
				{
					"reference_document": row.attendance or None,
					"date": row.date,
					"overtime_type": row.overtime_type,
					"overtime_duration": duration,
					"standard_working_hours": flt(row.standard_working_hours) or 8,
				},
			)
		if total <= 0:
			continue
		slip.total_overtime_duration = total
		try:
			slip.insert(ignore_permissions=True)
			slip.submit()
			created.append(slip.name)
			for row in employee_rows:
				row.created_overtime_slip = slip.name
				row.row_status = "Created"
				row.error_message = ""
		except Exception as exc:
			frappe.log_error(frappe.get_traceback(), "Batch Overtime Entry")
			for row in employee_rows:
				row.row_status = "Error"
				row.error_message = str(exc)

	created_rows = len([row for row in doc.details if row.created_overtime_slip])
	error_rows = len([row for row in doc.details if row.row_status in ("Error", "Skipped")])
	doc.created_slips = len(set(row.created_overtime_slip for row in doc.details if row.created_overtime_slip))
	doc.skipped_rows = error_rows
	doc.status = "Created" if created_rows and not error_rows else "Partly Created" if created_rows else "Fetched"
	doc.last_created_on = frappe.utils.now()
	doc.save(ignore_permissions=True)
	if doc.status == "Created" and doc.docstatus == 0:
		doc.submit()
	frappe.db.commit()

	return {
		"created": created,
		"created_slips": len(created),
		"created_rows": created_rows,
		"skipped_rows": error_rows,
	}
