import frappe
from frappe.utils import add_days, flt, getdate


def validate_hmo_enrollment(doc, method=None):
	if not doc.hmo_rate_plan:
		return

	plan = frappe.get_doc("HMO Rate Plan", doc.hmo_rate_plan)
	if plan.effective_from and not doc.effective_from:
		doc.effective_from = plan.effective_from
	if plan.effective_to and not doc.effective_to:
		doc.effective_to = plan.effective_to

	employee_rate = _get_employee_rate(plan, doc.employee_hmo_rate)
	if employee_rate:
		doc.level = employee_rate.level
		doc.mbl = flt(employee_rate.mbl)
		doc.employee_ee_monthly_cutoff = flt(employee_rate.ee_share_monthly_cutoff)
		doc.employee_er_monthly_cutoff = flt(employee_rate.er_share_monthly_cutoff)
		doc.employee_ee_weekly_cutoff = flt(employee_rate.ee_share_weekly_cutoff)
		doc.employee_er_weekly_cutoff = flt(employee_rate.er_share_weekly_cutoff)
	elif doc.employee_hmo_rate:
		frappe.throw(f"Employee HMO Rate {doc.employee_hmo_rate} was not found in {doc.hmo_rate_plan}.")

	for row in doc.get("dependents", []):
		if not row.dependent_hmo_rate:
			continue
		dependent_rate = _get_dependent_rate(plan, row.dependent_hmo_rate)
		if not dependent_rate:
			frappe.throw(f"Dependent HMO Rate {row.dependent_hmo_rate} was not found in {doc.hmo_rate_plan}.")
		row.mbl = flt(dependent_rate.mbl)
		row.dependent_ee_cutoff = flt(dependent_rate.ee_share_cutoff)
		row.dependent_ee_weekly = flt(dependent_rate.ee_share_weekly)

	validate_no_overlap(doc)


def validate_no_overlap(doc):
	if not doc.employee or not doc.effective_from:
		return

	new_start = getdate(doc.effective_from)
	new_end = getdate(doc.effective_to) if doc.effective_to else None
	existing = frappe.get_all(
		"Employee HMO Enrollment",
		filters={
			"employee": doc.employee,
			"name": ["!=", doc.name],
		},
		fields=["name", "effective_from", "effective_to"],
	)
	for row in existing:
		if not row.effective_from:
			continue
		old_start = getdate(row.effective_from)
		old_end = getdate(row.effective_to) if row.effective_to else None
		if _date_ranges_overlap(new_start, new_end, old_start, old_end):
			frappe.throw(
				f"Employee already has overlapping HMO Enrollment {row.name}. "
				"Close the previous enrollment before this effective date."
			)


def close_previous_enrollments(employee, effective_from, exclude_name=None):
	if not employee or not effective_from:
		return

	effective_from = getdate(effective_from)
	close_date = add_days(effective_from, -1)
	rows = frappe.get_all(
		"Employee HMO Enrollment",
		filters={
			"employee": employee,
			"effective_from": ["<", effective_from],
		},
		fields=["name", "effective_from", "effective_to"],
		order_by="effective_from desc, creation desc",
	)
	for row in rows:
		if exclude_name and row.name == exclude_name:
			continue
		if row.effective_to and getdate(row.effective_to) < effective_from:
			continue
		frappe.db.set_value("Employee HMO Enrollment", row.name, "effective_to", close_date, update_modified=False)


def _date_ranges_overlap(start_a, end_a, start_b, end_b):
	return start_a <= (end_b or getdate("9999-12-31")) and start_b <= (end_a or getdate("9999-12-31"))


def _get_employee_rate(plan, rate_key):
	for row in plan.get("employee_rates", []):
		if not row.is_active:
			continue
		if _employee_rate_key(row) == rate_key:
			return row
	return None


def _get_dependent_rate(plan, rate_key):
	for row in plan.get("dependent_rates", []):
		if not row.is_active:
			continue
		if _dependent_rate_key(row) == rate_key:
			return row
	return None


def _employee_rate_key(row):
	return f"{row.level}-{flt(row.mbl):g}"


def _dependent_rate_key(row):
	return f"Dependent-{flt(row.mbl):g}"
