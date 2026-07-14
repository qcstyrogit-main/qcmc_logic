import frappe
from frappe.utils import flt, getdate

from qcmc_logic.customs.salary_slip_employer_contributions import (
	set_component_amount,
	set_employer_component,
)


EMPLOYEE_COMPONENT = "HMO Premium"
EMPLOYER_COMPONENT = "HMO Employer Share"


def apply_hmo_deduction(doc, method=None):
	if not is_regular_employee(doc.employee):
		clear_hmo_rows(doc)
		return

	enrollment = get_active_hmo_enrollment(doc)
	if not enrollment:
		clear_hmo_rows(doc)
		return

	employee_amount, employer_amount = get_enrollment_cutoff_amounts(enrollment, doc)
	set_component_amount(doc, "deductions", EMPLOYEE_COMPONENT, employee_amount)
	set_employer_component(doc, EMPLOYER_COMPONENT, employer_amount)


def get_active_hmo_enrollment(doc):
	if not doc.employee or not doc.start_date or not doc.end_date:
		return None

	if not frappe.db.exists("DocType", "Employee HMO Enrollment"):
		return None

	start_date = getdate(doc.start_date)
	end_date = getdate(doc.end_date)

	enrollments = frappe.get_all(
		"Employee HMO Enrollment",
		filters={
			"employee": doc.employee,
			"effective_from": ["<=", end_date],
		},
		fields=[
			"name",
			"employee_hmo_rate",
			"employee_ee_monthly_cutoff",
			"employee_er_monthly_cutoff",
			"employee_ee_weekly_cutoff",
			"employee_er_weekly_cutoff",
			"payroll_type",
			"effective_from",
			"effective_to",
		],
		order_by="effective_from desc, creation desc",
	)

	for enrollment in enrollments:
		if enrollment.effective_to and getdate(enrollment.effective_to) < end_date:
			continue
		if enrollment.payroll_type and doc.payroll_frequency:
			if normalize_payroll_type(enrollment.payroll_type) != normalize_payroll_type(doc.payroll_frequency):
				continue
		return enrollment

	return None


def get_enrollment_cutoff_amounts(enrollment, doc):
	if is_weekly(doc, enrollment):
		employee_amount = flt(enrollment.employee_ee_weekly_cutoff)
		employer_amount = flt(enrollment.employee_er_weekly_cutoff)
	else:
		employee_amount = flt(enrollment.employee_ee_monthly_cutoff)
		employer_amount = flt(enrollment.employee_er_monthly_cutoff)

	employee_amount += get_dependent_cutoff_amount(enrollment.name, doc, weekly=is_weekly(doc, enrollment))
	return flt(employee_amount, 2), flt(employer_amount, 2)


def get_dependent_cutoff_amount(enrollment, doc, weekly=False):
	rows = frappe.get_all(
		"Employee HMO Dependent",
		filters={
			"parent": enrollment,
			"parenttype": "Employee HMO Enrollment",
			"is_active": 1,
		},
		fields=["dependent_ee_cutoff", "dependent_ee_weekly"],
	)
	if not rows:
		return 0

	fieldname = "dependent_ee_weekly" if weekly else "dependent_ee_cutoff"
	return sum(flt(row.get(fieldname)) for row in rows)


def is_weekly(doc, enrollment):
	return normalize_payroll_type(doc.payroll_frequency) == "Weekly" or normalize_payroll_type(
		enrollment.payroll_type
	) == "Weekly"


def is_regular_employee(employee):
	if not employee:
		return False

	employment_type = frappe.db.get_value("Employee", employee, "employment_type")
	return (employment_type or "").strip() == "Regular"


def normalize_payroll_type(value):
	value = (value or "").strip()
	if value in {"Bimonthly", "Semi Monthly", "Semi-Monthly"}:
		return "Monthly"
	return value


def clear_hmo_rows(doc):
	set_component_amount(doc, "deductions", EMPLOYEE_COMPONENT, 0)
	set_employer_component(doc, EMPLOYER_COMPONENT, 0)
