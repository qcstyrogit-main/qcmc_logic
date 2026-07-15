import calendar
import json
from pathlib import Path

import frappe
from frappe.utils import getdate


@frappe.whitelist()
def get_plan_year_history(plan_name, employee=None):
	plan = frappe.get_doc("HMO Rate Plan", plan_name)
	year_start, year_end = get_hmo_plan_year_window(plan.effective_from)

	plans = frappe.get_all(
		"HMO Rate Plan",
		filters={
			"company": plan.company,
			"effective_from": ["<=", year_end],
		},
		fields=["name", "effective_from", "effective_to"],
		order_by="effective_from asc, creation asc",
	)
	plan_names = [
		row.name
		for row in plans
		if not row.effective_to or getdate(row.effective_to) >= year_start
	]

	if not plan_names:
		plan_names = [plan.name]

	filters = {
		"hmo_rate_plan": ["in", plan_names],
		"effective_from": ["<=", year_end],
	}
	if employee:
		filters["employee"] = employee

	enrollments = frappe.get_all(
		"Employee HMO Enrollment",
		filters=filters,
		fields=[
			"name",
			"employee",
			"employee_name",
			"department",
			"payroll_type",
			"effective_from",
			"effective_to",
			"level",
			"mbl",
			"employee_hmo_rate",
			"hmo_rate_plan",
		],
		order_by="employee_name asc, effective_from asc, creation asc",
	)
	enrollments = [
		row
		for row in enrollments
		if not row.effective_to or getdate(row.effective_to) >= year_start
	]

	return frappe._dict(
		{
			"company": plan.company,
			"plan_year_start": year_start,
			"plan_year_end": year_end,
			"plan_names": plan_names,
			"enrollments": enrollments,
		}
		)


def get_hmo_plan_year_history(plan_name, employee=None):
	return get_plan_year_history(plan_name, employee)


def get_hmo_plan_year_window(effective_from):
	start_date = getdate(effective_from)
	if start_date.month >= 3:
		year = start_date.year
	else:
		year = start_date.year - 1

	year_start = getdate(f"{year}-03-01")
	last_feb_day = calendar.monthrange(year + 1, 2)[1]
	year_end = getdate(f"{year + 1}-02-{last_feb_day:02d}")
	return year_start, year_end


@frappe.whitelist()
def install_hmo_deduction_summary_print_format():
	fixture_path = Path(__file__).resolve().parents[1] / "fixtures" / "print_format.json"
	with fixture_path.open() as fixture:
		rows = json.load(fixture)

	print_format_data = next((row for row in rows if row.get("name") == "HMO Deduction Summary"), None)
	if not print_format_data:
		frappe.throw("HMO Deduction Summary print format was not found in fixtures.")

	if frappe.db.exists("Print Format", "HMO Deduction Summary"):
		doc = frappe.get_doc("Print Format", "HMO Deduction Summary")
		doc.update(print_format_data)
	else:
		doc = frappe.get_doc(print_format_data)

	doc.save(ignore_permissions=True)
	frappe.db.commit()
	return doc.name
