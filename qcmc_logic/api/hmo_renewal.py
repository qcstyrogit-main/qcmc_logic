import frappe
from frappe import _
from frappe.exceptions import DuplicateEntryError
from frappe.utils import cint, flt

from qcmc_logic.customs.hmo_enrollment import close_previous_enrollments


@frappe.whitelist()
def fetch_enrollments(renewal_name):
	doc = frappe.get_doc("Bulk HMO Enrollment Renewal", renewal_name)
	_validate_header(doc)

	old_plan = frappe.get_doc("HMO Rate Plan", doc.old_hmo_rate_plan)
	new_plan = frappe.get_doc("HMO Rate Plan", doc.new_hmo_rate_plan)
	new_employee_rates = {_employee_rate_key(row) for row in new_plan.get("employee_rates", []) if cint(row.is_active)}
	new_dependent_rates = {_dependent_rate_key(row) for row in new_plan.get("dependent_rates", []) if cint(row.is_active)}

	doc.set("details", [])
	enrollments = frappe.get_all(
		"Employee HMO Enrollment",
		filters={"hmo_rate_plan": old_plan.name, "is_active": 1},
		fields=[
			"name",
			"employee",
			"employee_name",
			"employee_hmo_rate",
			"payroll_type",
			"effective_from",
			"effective_to",
		],
		order_by="employee_name asc, employee asc",
	)

	for enrollment in enrollments:
		status = "Ready"
		message = ""
		new_rate = enrollment.employee_hmo_rate

		if new_rate not in new_employee_rates:
			status = "Skipped"
			message = _("Employee rate {0} is missing in {1}.").format(new_rate, new_plan.name)
		elif _has_existing_new_enrollment(enrollment.employee, doc.effective_from):
			status = "Skipped"
			message = _("Employee already has an HMO enrollment from {0}.").format(doc.effective_from)
		else:
			dependents = frappe.get_all(
				"Employee HMO Dependent",
				filters={
					"parent": enrollment.name,
					"parenttype": "Employee HMO Enrollment",
					"is_active": 1,
				},
				fields=["dependent_hmo_rate"],
			)
			missing_dependent = next(
				(row.dependent_hmo_rate for row in dependents if row.dependent_hmo_rate not in new_dependent_rates),
				None,
			)
			if missing_dependent:
				status = "Skipped"
				message = _("Dependent rate {0} is missing in {1}.").format(missing_dependent, new_plan.name)

		doc.append(
			"details",
			{
				"employee": enrollment.employee,
				"employee_name": enrollment.employee_name,
				"old_enrollment": enrollment.name,
				"old_employee_hmo_rate": enrollment.employee_hmo_rate,
				"new_employee_hmo_rate": new_rate,
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
def create_renewals(renewal_name):
	doc = frappe.get_doc("Bulk HMO Enrollment Renewal", renewal_name)
	_validate_header(doc)

	if not doc.get("details"):
		frappe.throw(_("Please fetch enrollments first."))

	for row in doc.get("details"):
		if row.status not in ("Ready", ""):
			continue

		existing = _has_existing_new_enrollment(row.employee, doc.effective_from)
		if existing:
			row.new_enrollment = existing
			row.status = "Skipped"
			row.message = _("Employee already has an HMO enrollment from {0}.").format(doc.effective_from)
			continue

		try:
			new_enrollment = _create_employee_enrollment(doc, row)
			row.new_enrollment = new_enrollment
			row.status = "Created"
			row.message = ""
		except DuplicateEntryError:
			existing = _has_existing_new_enrollment(row.employee, doc.effective_from)
			row.new_enrollment = existing or ""
			row.status = "Skipped"
			row.message = _("Employee already has an HMO enrollment from {0}.").format(doc.effective_from)
		except Exception as exc:
			row.status = "Error"
			row.message = str(exc)
			frappe.log_error(
				title=_("Bulk HMO Enrollment Renewal failed for {0}").format(row.employee),
				message=frappe.get_traceback(),
			)

	_update_summary(doc)
	doc.status = "Completed" if not any(row.status in ("Ready", "Error") for row in doc.get("details")) else "Fetched"
	doc.save(ignore_permissions=True)
	frappe.db.commit()
	return _summary(doc)


def _create_employee_enrollment(renewal, detail):
	old_doc = frappe.get_doc("Employee HMO Enrollment", detail.old_enrollment)
	close_previous_enrollments(old_doc.employee, renewal.effective_from)
	new_doc = frappe.new_doc("Employee HMO Enrollment")
	new_doc.employee = old_doc.employee
	new_doc.employee_name = old_doc.employee_name
	new_doc.company = old_doc.company
	new_doc.department = old_doc.department
	new_doc.payroll_type = old_doc.payroll_type
	new_doc.effective_from = renewal.effective_from
	new_doc.effective_to = renewal.effective_to
	new_doc.hmo_rate_plan = renewal.new_hmo_rate_plan
	new_doc.employee_hmo_rate = detail.new_employee_hmo_rate
	new_doc.is_active = 1

	for dependent in old_doc.get("dependents", []):
		if not cint(dependent.is_active):
			continue
		new_doc.append(
			"dependents",
			{
				"dependent_name": dependent.dependent_name,
				"relationship": dependent.relationship,
				"birth_date": dependent.birth_date,
				"dependent_hmo_rate": dependent.dependent_hmo_rate,
				"is_active": 1,
			},
		)

	new_doc.insert(ignore_permissions=True)
	return new_doc.name


def _validate_header(doc):
	for fieldname in ("old_hmo_rate_plan", "new_hmo_rate_plan", "effective_from"):
		if not doc.get(fieldname):
			frappe.throw(_("{0} is required.").format(frappe.unscrub(fieldname)))
	if doc.old_hmo_rate_plan == doc.new_hmo_rate_plan:
		frappe.throw(_("Old HMO Rate Plan and New HMO Rate Plan must be different."))


def _has_existing_new_enrollment(employee, effective_from, new_plan=None):
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
	doc.total_enrollments = total
	doc.created_enrollments = created
	doc.skipped_rows = skipped
	doc.error_rows = errors


def _summary(doc):
	return {
		"status": doc.status,
		"total_enrollments": cint(doc.total_enrollments),
		"created_enrollments": cint(doc.created_enrollments),
		"skipped_rows": cint(doc.skipped_rows),
		"error_rows": cint(doc.error_rows),
	}


def _employee_rate_key(row):
	return f"{row.level}-{flt(row.mbl):g}"


def _dependent_rate_key(row):
	return f"Dependent-{flt(row.mbl):g}"
