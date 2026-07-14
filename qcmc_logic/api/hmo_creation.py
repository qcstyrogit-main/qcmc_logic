import json

import frappe
from frappe import _
from frappe.exceptions import DuplicateEntryError
from frappe.utils import cint, flt

from qcmc_logic.customs.hmo_enrollment import close_previous_enrollments


@frappe.whitelist()
def fetch_employees(creation_name):
	doc = frappe.get_doc("Bulk HMO Enrollment Creation", creation_name)
	_validate_header(doc)

	doc.set("details", [])
	for employee in _get_employees(doc):
		status = "Needs Rate"
		message = _("Assign an Employee HMO Rate.")

		existing = _has_existing_enrollment(employee.name, doc.effective_from, doc.hmo_rate_plan)
		if existing:
			status = "Skipped"
			message = _("Employee already has an HMO enrollment for this effective date.")

		doc.append(
			"details",
			{
				"employee": employee.name,
				"employee_name": employee.employee_name,
				"department": employee.department,
				"branch": employee.branch,
				"payroll_type": employee.custom_payroll_type,
				"employee_hmo_rate": "",
				"status": status,
				"message": message,
			},
		)

	_update_summary(doc)
	doc.status = "Fetched"
	doc.save(ignore_permissions=True)
	frappe.db.commit()
	return _summary(doc)


@frappe.whitelist()
def create_enrollments(creation_name, selected_rows=None):
	doc = frappe.get_doc("Bulk HMO Enrollment Creation", creation_name)
	_validate_header(doc)

	if not doc.get("details"):
		frappe.throw(_("Please fetch employees first."))

	selected_row_names = _parse_selected_rows(selected_rows)
	for row in doc.get("details"):
		if selected_row_names and row.name not in selected_row_names:
			continue

		if row.status not in ("Ready", ""):
			continue

		if not row.employee_hmo_rate:
			row.status = "Error"
			row.message = _("Employee HMO Rate is required.")
			continue

		existing = _has_existing_enrollment(row.employee, doc.effective_from)
		if existing:
			row.enrollment = existing
			row.status = "Skipped"
			row.message = _("Employee already has an HMO enrollment for this effective date.")
			continue

		try:
			row.enrollment = _create_employee_enrollment(doc, row)
			row.status = "Created"
			row.message = ""
		except DuplicateEntryError:
			row.enrollment = _has_existing_enrollment(row.employee, doc.effective_from) or ""
			row.status = "Skipped"
			row.message = _("Employee already has an HMO enrollment for this effective date.")
		except Exception as exc:
			row.status = "Error"
			row.message = str(exc)
			frappe.log_error(
				title=_("Bulk HMO Enrollment Creation failed for {0}").format(row.employee),
				message=frappe.get_traceback(),
			)

	_update_summary(doc)
	doc.status = "Completed" if not any(row.status in ("Ready", "Error") for row in doc.get("details")) else "Fetched"
	doc.save(ignore_permissions=True)
	frappe.db.commit()
	return _summary(doc)


def _parse_selected_rows(selected_rows):
	if not selected_rows:
		return set()
	if isinstance(selected_rows, str):
		try:
			selected_rows = json.loads(selected_rows)
		except (TypeError, ValueError):
			selected_rows = []
	return {row for row in selected_rows if row}


def _get_employees(doc):
	filters = [
		["status", "=", "Active"],
		["company", "=", doc.company],
		["employment_type", "=", doc.employment_type],
	]
	if doc.payroll_type:
		filters.append(["custom_payroll_type", "=", doc.payroll_type])
	if doc.branch:
		filters.append(["branch", "=", doc.branch])
	if doc.department:
		filters.append(["department", "=", doc.department])
	if doc.employee_grade:
		filters.append(["grade", "=", doc.employee_grade])
	if doc.designation:
		filters.append(["designation", "=", doc.designation])

	filters.extend(_get_advanced_employee_filters(doc.get("advanced_filters")))

	return frappe.get_all(
		"Employee",
		filters=filters,
		fields=["name", "employee_name", "company", "department", "branch", "custom_payroll_type"],
		order_by="employee_name asc, name asc",
	)


def _get_advanced_employee_filters(raw_filters):
	if not raw_filters:
		return []

	try:
		filters = json.loads(raw_filters)
	except (TypeError, ValueError):
		return []

	employee_fields = {"name"} | {df.fieldname for df in frappe.get_meta("Employee").fields}
	advanced_filters = []
	for item in filters or []:
		fieldname = condition = value = None
		if isinstance(item, dict):
			fieldname = item.get("fieldname") or item.get("field")
			condition = item.get("condition") or item.get("operator") or "="
			value = item.get("value")
		elif isinstance(item, (list, tuple)):
			if len(item) >= 4 and item[0] == "Employee":
				fieldname, condition, value = item[1], item[2], item[3]
			elif len(item) >= 3:
				fieldname, condition, value = item[0], item[1], item[2]

		if fieldname in employee_fields and value not in (None, ""):
			advanced_filters.append([fieldname, condition or "=", value])

	return advanced_filters


def _create_employee_enrollment(creation, detail):
	employee = frappe.get_doc("Employee", detail.employee)
	close_previous_enrollments(employee.name, creation.effective_from)
	doc = frappe.new_doc("Employee HMO Enrollment")
	doc.employee = employee.name
	doc.employee_name = employee.employee_name
	doc.company = employee.company
	doc.department = employee.department
	doc.payroll_type = employee.custom_payroll_type
	doc.effective_from = creation.effective_from
	doc.effective_to = creation.effective_to
	doc.hmo_rate_plan = creation.hmo_rate_plan
	doc.employee_hmo_rate = detail.employee_hmo_rate
	doc.is_active = 1
	doc.insert(ignore_permissions=True)
	return doc.name


def _validate_header(doc):
	for fieldname in ("hmo_rate_plan", "company", "employment_type", "effective_from"):
		if not doc.get(fieldname):
			frappe.throw(_("{0} is required.").format(frappe.unscrub(fieldname)))


def _has_existing_enrollment(employee, effective_from, hmo_rate_plan=None):
	expected_name = f"HMO-{employee}-{effective_from}"
	if frappe.db.exists("Employee HMO Enrollment", expected_name):
		return expected_name

	existing = frappe.db.exists(
		"Employee HMO Enrollment",
		{
			"employee": employee,
			"effective_from": effective_from,
		},
	)
	if existing:
		return existing

	return None


def _update_summary(doc):
	total = len(doc.get("details") or [])
	created = len([row for row in doc.get("details") if row.status == "Created"])
	skipped = len([row for row in doc.get("details") if row.status == "Skipped"])
	errors = len([row for row in doc.get("details") if row.status == "Error"])
	doc.total_employees = total
	doc.created_enrollments = created
	doc.skipped_rows = skipped
	doc.error_rows = errors


def _summary(doc):
	return {
		"status": doc.status,
		"total_employees": cint(doc.total_employees),
		"created_enrollments": cint(doc.created_enrollments),
		"skipped_rows": cint(doc.skipped_rows),
		"error_rows": cint(doc.error_rows),
	}


def _employee_rate_key(row):
	return f"{row.level}-{flt(row.mbl):g}"
