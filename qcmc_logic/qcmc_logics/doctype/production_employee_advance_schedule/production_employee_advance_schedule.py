from __future__ import annotations

from collections import defaultdict
from datetime import datetime, time, timedelta

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, getdate, now_datetime, today

from qcmc_logic.qcmc_logics.doctype.production_plantilla.production_plantilla import (
	validate_section_machine,
	validate_warehouse,
)


COMPANY_CREATOR_ROLES = {
	"Multiplast Corporation": {"Production - MC"},
	"QC Styropackaging Corporation": {"Production - SMB", "Production - STCLA"},
}
COMPANY_APPROVER_ROLES = {
	"Multiplast Corporation": {"Plant Manager MC"},
	"QC Styropackaging Corporation": {"Plant Manager QC"},
}
PRIVILEGED_ROLES = {"Administrator", "System Manager", "HR User"}
STRICT_WORKFLOW_STATES = {"For Approval", "Approved for Posting", "Posted / Active"}
DAY_NAMES = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
SHIFT_PREFIXES = ("day_shift", "night_shift")


class ProductionEmployeeAdvanceSchedule(Document):
	def validate(self):
		self._validate_company_actor()
		self._validate_dates()
		validate_warehouse(self.company, self.warehouse)
		self._set_workflow_audit()
		self._validate_schedule_rows()
		if self.workflow_state in STRICT_WORKFLOW_STATES:
			self._validate_complete_coverage()
			self._validate_duplicate_schedule()
			self._validate_external_employee_conflicts()

	def before_submit(self):
		if self.workflow_state != "Posted / Active":
			frappe.throw(_("Only a schedule in Posted / Active state can be submitted."))

	def _validate_company_actor(self):
		if self.company not in COMPANY_CREATOR_ROLES:
			frappe.throw(_("Company {0} is not configured for this schedule.").format(self.company))

		roles = set(frappe.get_roles())
		if frappe.session.user == "Administrator" or roles & PRIVILEGED_ROLES:
			return

		allowed_roles = COMPANY_CREATOR_ROLES[self.company] | COMPANY_APPROVER_ROLES[self.company]
		if not roles & allowed_roles:
			frappe.throw(
				_("Your roles are not authorized for Company {0}.").format(
					frappe.bold(self.company)
				),
				frappe.PermissionError,
			)

	def _validate_dates(self):
		validate_week_dates(self.date_start, self.date_end)

	def _set_workflow_audit(self):
		previous = self.get_doc_before_save()
		previous_state = previous.workflow_state if previous else None
		if self.workflow_state == previous_state:
			return

		if self.workflow_state == "Approved for Posting":
			self.approved_by = frappe.session.user
			self.approved_on = now_datetime()
		elif self.workflow_state == "Posted / Active":
			self.posted_by = frappe.session.user
			self.posted_on = now_datetime()
			self.posting_date = today()

	def _validate_schedule_rows(self):
		shift_cache: dict[str, tuple[time | timedelta, time | timedelta]] = {}
		assignments = []
		slot_structures = {}
		employee_restdays = {}
		for row in self.schedule_details:
			self._validate_structure(row)
			slot_key = (row.plantilla_id, row.plantilla_slot)
			structure = (
				row.section,
				row.machine,
				(row.production_position or "").strip().casefold(),
				row.production_plantilla if row.row_source == "Plantilla" else None,
			)
			if slot_key in slot_structures and slot_structures[slot_key] != structure:
				frappe.throw(
					_("Plantilla {0}, Slot {1} is used for different structures.").format(*slot_key)
				)
			slot_structures[slot_key] = structure
			for prefix in SHIFT_PREFIXES:
				assignments.extend(self._validate_shift_half(row, prefix, shift_cache))
				self._validate_consistent_restday(row, prefix, employee_restdays)
		_validate_overlapping_assignments(assignments)

	def _validate_consistent_restday(self, row, prefix, employee_restdays):
		is_day = prefix == "day_shift"
		status = row.get("ds_assignment_status" if is_day else "ns_assignment_status")
		employee = row.get("day_shift_employee" if is_day else "night_shift_employee")
		restday = row.get("day_shift_restday" if is_day else "night_shift_restday")
		if status != "Assigned" or not employee:
			return
		key = (employee, prefix)
		rest_date = getdate(restday)
		if key in employee_restdays and employee_restdays[key] != rest_date:
			frappe.throw(
				_("Employee {0} has inconsistent {1} Restdays.").format(
					frappe.bold(employee),
					"Day Shift" if is_day else "Night Shift",
				)
			)
		employee_restdays[key] = rest_date

	def _validate_structure(self, row):
		if not row.plantilla_id or row.plantilla_id < 1:
			frappe.throw(_("Row {0}: Plantilla ID must be positive.").format(row.idx))
		if not row.plantilla_slot or row.plantilla_slot < 1:
			frappe.throw(_("Row {0}: Plantilla Slot must be positive.").format(row.idx))

		validate_section_machine(self.warehouse, row.section, row.machine)
		row.production_position = (row.production_position or "").strip()
		if not row.production_position:
			frappe.throw(_("Row {0}: Production Position is required.").format(row.idx))

		if row.row_source == "Plantilla":
			if not row.production_plantilla:
				frappe.throw(_("Row {0}: Production Plantilla is required.").format(row.idx))
			plantilla = frappe.db.get_value(
				"Production Plantilla",
				row.production_plantilla,
				[
					"warehouse",
					"section",
					"machine",
					"production_position",
					"plantilla_id",
					"plantilla_slot",
					"is_active",
				],
				as_dict=True,
			)
			if not plantilla or not plantilla.is_active:
				frappe.throw(_("Row {0}: Production Plantilla is missing or inactive.").format(row.idx))
			expected = (
				self.warehouse,
				row.section,
				row.machine,
				row.production_position.strip().casefold(),
				row.plantilla_id,
				row.plantilla_slot,
			)
			actual = (
				plantilla.warehouse,
				plantilla.section,
				plantilla.machine,
				(plantilla.production_position or "").strip().casefold(),
				plantilla.plantilla_id,
				plantilla.plantilla_slot,
			)
			if expected != actual:
				frappe.throw(_("Row {0}: values do not match Production Plantilla.").format(row.idx))
		elif row.production_plantilla:
			frappe.throw(_("Row {0}: a Manual row cannot reference Production Plantilla.").format(row.idx))

	def _validate_shift_half(self, row, prefix, shift_cache):
		is_day = prefix == "day_shift"
		status_field = "ds_assignment_status" if is_day else "ns_assignment_status"
		employee_field = "day_shift_employee" if is_day else "night_shift_employee"
		restday_field = "day_shift_restday" if is_day else "night_shift_restday"
		status = row.get(status_field)
		employee = row.get(employee_field)
		restday = row.get(restday_field)
		active_fields = [
			(f"{prefix}_{day_name}", row.get(f"{prefix}_{day_name}"))
			for day_name in DAY_NAMES
			if getdate(add_days(self.date_start, DAY_NAMES.index(day_name))) <= getdate(self.date_end)
		]
		inactive_fields = [
			f"{prefix}_{day_name}"
			for day_name in DAY_NAMES
			if getdate(add_days(self.date_start, DAY_NAMES.index(day_name))) > getdate(self.date_end)
		]
		for fieldname in inactive_fields:
			if row.get(fieldname):
				frappe.throw(
					_("Row {0}: {1} falls outside Date End.").format(
						row.idx, frappe.bold(frappe.unscrub(fieldname))
					)
				)

		has_shifts = any(shift_type for _, shift_type in active_fields)
		if not status and not employee and not restday and not has_shifts:
			return []
		if not status:
			frappe.throw(_("Row {0}: {1} is required.").format(row.idx, frappe.unscrub(status_field)))
		if not has_shifts:
			frappe.throw(
				_("Row {0}: select at least one {1} Shift Type.").format(
					row.idx, "Day" if is_day else "Night"
				)
			)
		if status == "Assigned":
			if not employee:
				frappe.throw(
					_("Row {0}: {1} is required for Assigned status.").format(
						row.idx, frappe.unscrub(employee_field)
					)
				)
			self._validate_employee(row, employee)
			if not restday:
				frappe.throw(
					_("Row {0}: Restday is required for an Assigned employee.").format(row.idx)
				)
		elif employee:
			frappe.throw(
				_("Row {0}: Employee must be empty for {1}.").format(row.idx, frappe.bold(status))
			)

		if restday:
			rest_date = getdate(restday)
			if not getdate(self.date_start) <= rest_date <= getdate(self.date_end):
				frappe.throw(_("Row {0}: Restday must be within the schedule period.").format(row.idx))
			rest_field = f"{prefix}_{DAY_NAMES[rest_date.weekday()]}"
			if row.get(rest_field):
				frappe.throw(
					_("Row {0}: {1} must be empty because it is the Restday.").format(
						row.idx, frappe.unscrub(rest_field)
					)
				)
		if status == "PLAN STOP" and restday:
			frappe.throw(_("Row {0}: PLAN STOP cannot have a Restday.").format(row.idx))

		assignments = []
		if status != "Assigned":
			return assignments
		for fieldname, shift_type in active_fields:
			if not shift_type:
				continue
			day_index = DAY_NAMES.index(fieldname.rsplit("_", 1)[1])
			schedule_date = getdate(add_days(self.date_start, day_index))
			start, end = _get_shift_times(shift_type, shift_cache)
			start_dt, end_dt = _make_interval(schedule_date, start, end)
			assignments.append(
				{
					"employee": employee,
					"start": start_dt,
					"end": end_dt,
					"row": row.idx,
					"fieldname": fieldname,
				}
			)
		return assignments

	def _validate_employee(self, row, employee):
		employee_row = frappe.db.get_value(
			"Employee",
			employee,
			["status", "company"],
			as_dict=True,
		)
		if not employee_row or employee_row.status != "Active":
			frappe.throw(_("Row {0}: Employee {1} must be Active.").format(row.idx, employee))
		if employee_row.company and employee_row.company != self.company:
			frappe.throw(
				_("Row {0}: Employee {1} does not belong to Company {2}.").format(
					row.idx, employee, self.company
				)
			)

	def _validate_complete_coverage(self):
		coverage = defaultdict(int)
		for row in self.schedule_details:
			slot = (row.plantilla_id, row.plantilla_slot)
			for prefix in SHIFT_PREFIXES:
				for day_index, day_name in enumerate(DAY_NAMES):
					if getdate(add_days(self.date_start, day_index)) > getdate(self.date_end):
						continue
					if row.get(f"{prefix}_{day_name}"):
						coverage[(slot, prefix, day_index)] += 1

		slots = {(row.plantilla_id, row.plantilla_slot) for row in self.schedule_details}
		for slot in slots:
			for prefix in SHIFT_PREFIXES:
				for day_index, day_name in enumerate(DAY_NAMES):
					if getdate(add_days(self.date_start, day_index)) > getdate(self.date_end):
						continue
					count = coverage[(slot, prefix, day_index)]
					if count == 0:
						frappe.throw(
							_("Plantilla {0}, Slot {1} has no {2} coverage on {3}.").format(
								slot[0],
								slot[1],
								"Day Shift" if prefix == "day_shift" else "Night Shift",
								day_name.title(),
							)
						)
					if count > 1:
						frappe.throw(
							_("Plantilla {0}, Slot {1} has duplicate {2} coverage on {3}.").format(
								slot[0],
								slot[1],
								"Day Shift" if prefix == "day_shift" else "Night Shift",
								day_name.title(),
							)
						)

	def _validate_duplicate_schedule(self):
		existing = frappe.get_all(
			"Production Employee Advance Schedule",
			filters={
				"name": ("!=", self.name or ""),
				"warehouse": self.warehouse,
				"docstatus": ("<", 2),
				"workflow_state": ("in", tuple(STRICT_WORKFLOW_STATES)),
				"date_start": ("<=", self.date_end),
				"date_end": (">=", self.date_start),
			},
			pluck="name",
			limit=1,
		)
		if existing:
			frappe.throw(
				_("Schedule overlaps with {0} for Warehouse {1}.").format(
					frappe.bold(existing[0]), frappe.bold(self.warehouse)
				)
			)

	def _validate_external_employee_conflicts(self):
		# Cross-document conflict checking is deliberately delegated to the same
		# interval builder so overnight shifts are compared as real datetimes.
		parents = frappe.get_all(
			"Production Employee Advance Schedule",
			filters={
				"name": ("!=", self.name or ""),
				"docstatus": ("<", 2),
				"workflow_state": ("in", tuple(STRICT_WORKFLOW_STATES)),
				"date_start": ("<=", self.date_end),
				"date_end": (">=", self.date_start),
			},
			fields=["name", "date_start", "date_end"],
		)
		if not parents:
			return

		employees = {
			row.day_shift_employee
			for row in self.schedule_details
			if row.ds_assignment_status == "Assigned" and row.day_shift_employee
		} | {
			row.night_shift_employee
			for row in self.schedule_details
			if row.ns_assignment_status == "Assigned" and row.night_shift_employee
		}
		if not employees:
			return

		other_assignments = _load_external_assignments(parents, employees)
		current_assignments = _collect_assigned_intervals(self)
		for current in current_assignments:
			for other in other_assignments.get(current["employee"], []):
				if current["start"] < other["end"] and other["start"] < current["end"]:
					frappe.throw(
						_("Employee {0} conflicts with schedule {1}.").format(
							frappe.bold(current["employee"]),
							frappe.bold(other["parent"]),
						)
					)


def get_creator_roles_for_company(company: str) -> set[str]:
	return COMPANY_CREATOR_ROLES.get(company, set())


def get_approver_roles_for_company(company: str) -> set[str]:
	return COMPANY_APPROVER_ROLES.get(company, set())


def validate_week_dates(date_start, date_end):
	start = getdate(date_start)
	end = getdate(date_end)
	if start.weekday() != 0:
		frappe.throw(_("Date Start must be a Monday for the Monday-to-Sunday layout."))
	if end < start:
		frappe.throw(_("Date End cannot be earlier than Date Start."))
	if end > getdate(add_days(start, 6)):
		frappe.throw(_("A schedule cannot extend beyond the Sunday of its starting week."))


def _get_shift_times(shift_type, cache):
	if shift_type not in cache:
		value = frappe.db.get_value("Shift Type", shift_type, ["start_time", "end_time"], as_dict=True)
		if not value or value.start_time is None or value.end_time is None:
			frappe.throw(_("Shift Type {0} has invalid Start or End Time.").format(shift_type))
		cache[shift_type] = (value.start_time, value.end_time)
	return cache[shift_type]


def _time_as_timedelta(value) -> timedelta:
	if isinstance(value, timedelta):
		return value
	if isinstance(value, time):
		return timedelta(hours=value.hour, minutes=value.minute, seconds=value.second)
	if isinstance(value, str):
		parsed = datetime.strptime(value, "%H:%M:%S").time()
		return timedelta(hours=parsed.hour, minutes=parsed.minute, seconds=parsed.second)
	raise ValueError(f"Unsupported time value: {value!r}")


def _make_interval(schedule_date, start, end):
	day_start = datetime.combine(getdate(schedule_date), time.min)
	start_delta = _time_as_timedelta(start)
	end_delta = _time_as_timedelta(end)
	start_dt = day_start + start_delta
	end_dt = day_start + end_delta
	if end_delta <= start_delta:
		end_dt += timedelta(days=1)
	return start_dt, end_dt


def _validate_overlapping_assignments(assignments):
	by_employee = defaultdict(list)
	for assignment in assignments:
		by_employee[assignment["employee"]].append(assignment)
	for employee, employee_assignments in by_employee.items():
		employee_assignments.sort(key=lambda row: row["start"])
		for previous, current in zip(employee_assignments, employee_assignments[1:]):
			if current["start"] < previous["end"]:
				frappe.throw(
					_("Employee {0} has overlapping assignments in rows {1} and {2}.").format(
						frappe.bold(employee), previous["row"], current["row"]
					)
				)


def _collect_assigned_intervals(doc):
	cache = {}
	result = []
	for row in doc.schedule_details:
		for prefix, status_field, employee_field in (
			("day_shift", "ds_assignment_status", "day_shift_employee"),
			("night_shift", "ns_assignment_status", "night_shift_employee"),
		):
			if row.get(status_field) != "Assigned" or not row.get(employee_field):
				continue
			for day_index, day_name in enumerate(DAY_NAMES):
				schedule_date = getdate(add_days(doc.date_start, day_index))
				if schedule_date > getdate(doc.date_end):
					continue
				shift_type = row.get(f"{prefix}_{day_name}")
				if not shift_type:
					continue
				start, end = _get_shift_times(shift_type, cache)
				start_dt, end_dt = _make_interval(schedule_date, start, end)
				result.append(
					{
						"employee": row.get(employee_field),
						"start": start_dt,
						"end": end_dt,
						"row": row.idx,
					}
				)
	return result


def _load_external_assignments(parents, employees):
	result = defaultdict(list)
	for parent in parents:
		doc = frappe.get_doc("Production Employee Advance Schedule", parent.name)
		for assignment in _collect_assigned_intervals(doc):
			if assignment["employee"] in employees:
				assignment["parent"] = parent.name
				result[assignment["employee"]].append(assignment)
	return result


@frappe.whitelist()
def get_plantilla_rows(company: str, warehouse: str, date_start: str | None = None):
	validate_warehouse(company, warehouse)
	if frappe.session.user != "Administrator" and not frappe.has_permission(
		"Warehouse", ptype="read", doc=warehouse
	):
		frappe.throw(_("You are not permitted to access Warehouse {0}.").format(warehouse), frappe.PermissionError)
	schedule_date = getdate(date_start or today())
	all_rows = frappe.get_list(
		"Production Plantilla",
		filters={"company": company, "warehouse": warehouse, "is_active": 1},
		fields=[
			"name",
			"section",
			"machine",
			"production_position",
			"plantilla_id",
			"plantilla_slot",
			"position_order",
			"effective_from",
			"effective_to",
		],
		order_by="plantilla_id asc, position_order asc, plantilla_slot asc",
	)
	return [
		row
		for row in all_rows
		if (not row.effective_from or getdate(row.effective_from) <= schedule_date)
		and (not row.effective_to or getdate(row.effective_to) >= schedule_date)
	]
