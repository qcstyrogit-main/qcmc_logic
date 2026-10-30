from __future__ import annotations

import re

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, getdate


DAY_FIELDS = (
	"monday",
	"tuesday",
	"wednesday",
	"thursday",
	"friday",
	"saturday",
	"sunday",
)
SHIFT_HALVES = ("day_shift", "night_shift")
SCHEDULED_DAY_STATUSES = {"check", "v"}
VALID_DAY_STATUSES = {"NW", "RD", "PW", "X"}
EXCLUDED_COST_CENTER_MARKERS = ("EPS", "PSP")


class WeeklyManpowerSchedule(Document):
	def validate(self):
		self._validate_week()
		if not self.flags.get("skip_section_validation"):
			self._validate_section()
		self._validate_rows()

	def before_submit(self):
		if self.workflow_state != "Active":
			frappe.throw(_("Only an Active manpower schedule can be submitted."))
		if not self.schedule_details:
			frappe.throw(_("Add schedule details in the Schedule Workbench before activating."))

	def on_submit(self):
		created = 0
		for row in self.schedule_details:
			for shift_half in SHIFT_HALVES:
				if row.get(f"{shift_half}_ps"):
					continue
				employee = row.get(f"{shift_half}_employee")
				shift_type = row.get(f"{shift_half}_type")
				statuses = [row.get(f"{shift_half}_{day}") for day in DAY_FIELDS]
				for start_date, end_date in get_checked_date_ranges(self.week_start, statuses):
					if assignment_exists(employee, shift_type, start_date, end_date):
						continue
					assignment = frappe.get_doc({
						"doctype": "Shift Assignment",
						"employee": employee,
						"company": self.company,
						"shift_type": shift_type,
						"start_date": start_date,
						"end_date": end_date,
					})
					assignment.insert()
					assignment.submit()
					created += 1

		frappe.msgprint(_("Created {0} Shift Assignment(s). Existing exact matches were skipped.").format(created))

	def _validate_week(self):
		if not self.week_start:
			frappe.throw(_("Week Start is required."))
		self.week_start = getdate(self.week_start)
		if self.week_start.weekday() != 0:
			frappe.throw(_("Week Start must be a Monday."))
		self.week_end = add_days(self.week_start, 6)

	def _validate_section(self):
		section = frappe.db.get_value(
			"Cost Center",
			self.section,
			["company", "disabled", "is_group", "cost_center_name"],
			as_dict=True,
		)
		if not section or section.disabled or section.is_group:
			frappe.throw(_("Section must be an enabled leaf Cost Center."))
		if section.company != self.company:
			frappe.throw(_("Section Cost Center must belong to the selected Company."))
		if has_excluded_cost_center_marker(section.cost_center_name):
			frappe.throw(_("Cost Centers containing EPS or PSP are excluded from manpower schedules."))

		if frappe.get_meta("Cost Center").has_field("remarks"):
			remarks = frappe.db.get_value("Cost Center", self.section, "remarks")
			if has_excluded_cost_center_marker(remarks):
				frappe.throw(_("Cost Centers with EPS or PSP in Remarks are excluded from manpower schedules."))

	def _validate_rows(self):
		self.schedule_details = sort_schedule_detail_rows(
			self.schedule_details, getattr(self, "company", None)
		)
		if not self.schedule_details:
			if self.workflow_state == "Draft":
				return
			frappe.throw(_("Add schedule details in the Schedule Workbench before activating."))

		for row in self.schedule_details:
			for shift_half in SHIFT_HALVES:
				for day in DAY_FIELDS:
					fieldname = f"{shift_half}_{day}"
					try:
						status = normalize_day_status(row.get(fieldname))
					except ValueError:
						frappe.throw(
							_("Row {0}: {1} must be PW, NW, RD, or X.").format(
								row.idx, day.title()
							)
						)
					row.set(fieldname, status)

				if row.get(f"{shift_half}_ps"):
					continue
				employee_name = row.get(f"{shift_half}_employee")
				shift_type = row.get(f"{shift_half}_type")
				if not employee_name:
					if shift_type:
						frappe.throw(
							_("Row {0}: {1} schedule fields require an Employee.").format(
								row.idx, shift_half.replace("_", " ").title()
							)
						)
					continue

				employee = frappe.db.get_value(
					"Employee",
					employee_name,
					["status", "company"],
					as_dict=True,
				)
				if not employee or employee.status != "Active":
					frappe.throw(_("Row {0}: Employee must be active.").format(row.idx))
				if employee.company and employee.company != self.company:
					frappe.throw(_("Row {0}: Employee must belong to Company {1}.").format(row.idx, self.company))
				if not shift_type:
					frappe.throw(_("Row {0}: Shift Type is required for {1}.").format(
						row.idx, shift_half.replace("_", " ").title()
					))


def normalize_day_status(value):
	status = str(value or "").strip().upper()
	if not status:
		return "X"
	if status not in VALID_DAY_STATUSES:
		raise ValueError("Invalid manpower schedule day status")
	return status


def sort_schedule_detail_rows(rows, company):
	def natural_key(value):
		return tuple(
			(1, int(part)) if part.isdigit() else (0, part.casefold())
			for part in re.split(r"(\d+)", str(value or ""))
		)

	def get_value(row, fieldname):
		return row.get(fieldname) if hasattr(row, "get") else getattr(row, fieldname, None)

	return sorted(
		rows,
		key=lambda row: (
			natural_key(company),
			natural_key(get_value(row, "location")),
			natural_key(get_value(row, "sortingno")),
		),
	)


def get_checked_date_ranges(start_date, day_statuses):
	"""Return contiguous date ranges marked V/v or Check."""
	checked_dates = [
		getdate(add_days(start_date, day_index))
		for day_index, status in enumerate(day_statuses)
		if (status or "").strip().casefold() in SCHEDULED_DAY_STATUSES
	]
	if not checked_dates:
		return []

	ranges = []
	range_start = previous_date = checked_dates[0]
	for schedule_date in checked_dates[1:]:
		if (schedule_date - previous_date).days > 1:
			ranges.append((range_start, previous_date))
			range_start = schedule_date
		previous_date = schedule_date
	ranges.append((range_start, previous_date))
	return ranges


def has_excluded_cost_center_marker(value):
	value = (value or "").upper()
	return any(re.search(rf"\b{marker}\b", value) for marker in EXCLUDED_COST_CENTER_MARKERS)


def assignment_exists(employee, shift_type, start_date, end_date):
	existing_assignments = frappe.get_all(
		"Shift Assignment",
		filters=[
			["employee", "=", employee],
			["docstatus", "=", 1],
			["status", "=", "Active"],
			["start_date", "<=", end_date],
		],
		or_filters=[
			["end_date", ">=", start_date],
			["end_date", "is", "not set"],
		],
		fields=["shift_type", "start_date", "end_date"],
	)
	for existing in existing_assignments:
		if (
			existing.shift_type == shift_type
			and getdate(existing.start_date) <= getdate(start_date)
			and (not existing.end_date or getdate(existing.end_date) >= getdate(end_date))
		):
			return True
		frappe.throw(
			_("Employee {0} already has a Shift Assignment overlapping {1} to {2}.").format(
				employee, start_date, end_date
			)
		)
	return False


@frappe.whitelist()
def get_cost_centers(doctype, txt, searchfield, start, page_len, filters=None):
	filters = frappe.parse_json(filters) if isinstance(filters, str) else (filters or {})
	company = filters.get("company")
	if not company:
		return []

	fields = ["name", "cost_center_name"]
	if frappe.get_meta("Cost Center").has_field("remarks"):
		fields.append("remarks")
	rows = frappe.get_list(
		"Cost Center",
		filters={"company": company, "disabled": 0, "is_group": 0},
		fields=fields,
		order_by="cost_center_name asc",
		limit_page_length=int(start or 0) + int(page_len or 20),
	)
	search_text = (txt or "").casefold()
	return [
		[row.name, row.cost_center_name]
		for row in rows
		if not has_excluded_cost_center_marker(row.cost_center_name)
		and not has_excluded_cost_center_marker(row.get("remarks"))
		and (not search_text or search_text in row.name.casefold() or search_text in row.cost_center_name.casefold())
	][int(start or 0):int(start or 0) + int(page_len or 20)]


@frappe.whitelist()
def get_active_employees(company, cost_center):
	if not company or not cost_center:
		frappe.throw(_("Company and Section are required."))
	_validate_cost_center(company, cost_center)

	filters = {"company": company, "status": "Active"}
	employee_meta = frappe.get_meta("Employee")
	if employee_meta.has_field("cost_center"):
		filters["cost_center"] = cost_center
	elif employee_meta.has_field("default_cost_center"):
		filters["default_cost_center"] = cost_center

	employee_fields = ["name", "employee_name", "designation"]
	if employee_meta.has_field("default_shift"):
		employee_fields.append("default_shift")
	if employee_meta.has_field("branch"):
		employee_fields.append("branch")

	return frappe.get_list(
		"Employee",
		filters=filters,
		fields=employee_fields,
		order_by="employee_name asc",
	)


@frappe.whitelist()
def get_schedule_workbench_data(name):
	doc = frappe.get_doc("Weekly Manpower Schedule", name)
	doc.check_permission("read")
	can_edit = doc.docstatus == 0 and doc.workflow_state == "Draft" and doc.has_permission("write")

	return {
		"name": doc.name,
		"company": doc.company,
		"section": doc.section,
		"week_start": str(doc.week_start or ""),
		"week_end": str(doc.week_end or ""),
		"workflow_state": doc.workflow_state,
		"can_edit": can_edit,
		"rows": [
			row.as_dict()
			for row in sort_schedule_detail_rows(doc.schedule_details, doc.company)
		],
		"employees": get_active_employees(doc.company, doc.section) if can_edit else [],
		"shift_types": (
			frappe.get_list("Shift Type", fields=["name"], order_by="name asc", limit_page_length=1000)
			if can_edit
			else []
		),
	}


@frappe.whitelist()
def save_schedule_workbench(name, rows):
	doc = frappe.get_doc("Weekly Manpower Schedule", name)
	doc.check_permission("write")
	if doc.docstatus != 0 or doc.workflow_state != "Draft":
		frappe.throw(_("Only Draft schedules can be edited in the Schedule Workbench."))

	rows = frappe.parse_json(rows) if isinstance(rows, str) else rows
	if not isinstance(rows, list):
		frappe.throw(_("Schedule details must be a list of rows."))

	fields = [
		"sortingno",
		"location",
		"section",
		"position",
		"machine",
		"day_shift_type",
		"day_shift_employee",
		"day_shift_ps",
		"day_shift_nosched_code",
		"day_shift_monday",
		"day_shift_tuesday",
		"day_shift_wednesday",
		"day_shift_thursday",
		"day_shift_friday",
		"day_shift_saturday",
		"day_shift_sunday",
		"night_shift_type",
		"night_shift_employee",
		"night_shift_ps",
		"night_shift_nosched_code",
		"night_shift_monday",
		"night_shift_tuesday",
		"night_shift_wednesday",
		"night_shift_thursday",
		"night_shift_friday",
		"night_shift_saturday",
		"night_shift_sunday",
	]
	doc.set("schedule_details", [])
	for row in rows:
		if not isinstance(row, dict):
			frappe.throw(_("Each schedule detail must be a row object."))
		values = {fieldname: row.get(fieldname) for fieldname in fields}
		for shift_half in SHIFT_HALVES:
			if frappe.utils.cint(values.get(f"{shift_half}_ps")):
				values[f"{shift_half}_employee"] = None
				values[f"{shift_half}_nosched_code"] = "NOSCHED"
			else:
				values[f"{shift_half}_nosched_code"] = None
				employee = values.get(f"{shift_half}_employee")
				values[f"{shift_half}_employee_name"] = (
					frappe.db.get_value("Employee", employee, "employee_name") if employee else None
				)
		doc.append("schedule_details", values)

	doc.schedule_details = sort_schedule_detail_rows(doc.schedule_details, doc.company)
	doc.flags.skip_section_validation = True
	doc.save()
	return {"name": doc.name, "modified": str(doc.modified), "doc": doc.as_dict()}


def _validate_cost_center(company, cost_center):
	center = frappe.db.get_value(
		"Cost Center",
		cost_center,
		["company", "disabled", "is_group", "cost_center_name"],
		as_dict=True,
	)
	if not center or center.company != company or center.disabled or center.is_group:
		frappe.throw(_("Select an enabled leaf Cost Center belonging to the Company."))
	if has_excluded_cost_center_marker(center.cost_center_name):
		frappe.throw(_("Cost Centers containing EPS or PSP are excluded from manpower schedules."))
	if frappe.get_meta("Cost Center").has_field("remarks"):
		remarks = frappe.db.get_value("Cost Center", cost_center, "remarks")
		if has_excluded_cost_center_marker(remarks):
			frappe.throw(_("Cost Centers with EPS or PSP in Remarks are excluded from manpower schedules."))