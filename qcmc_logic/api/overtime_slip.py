import frappe
from frappe import _
from frappe.utils import flt, getdate

from qcmc_logic.customs.overtime_policy import normalize_overtime_duration
from qcmc_logic.customs.rest_day import get_employee_roster_work_days, is_rest_day_from_work_days

DEFAULT_REGULAR_OT_TYPE = "Regular OT"
DEFAULT_REST_DAY_OT_TYPE = "Rest Day OT"
DEFAULT_HOLIDAY_OT_TYPE = "Regular Holiday OT"


def _get_employee_holiday_dates(employee, start_date, end_date):
	employee_doc = frappe.db.get_value(
		"Employee",
		employee,
		["company", "holiday_list"],
		as_dict=True,
	)
	if not employee_doc:
		return set()

	holiday_list = employee_doc.holiday_list or frappe.db.get_value(
		"Company", employee_doc.company, "default_holiday_list"
	)
	if not holiday_list:
		return set()

	return {
		str(holiday.holiday_date)
		for holiday in frappe.get_all(
			"Holiday",
			filters={"parent": holiday_list, "holiday_date": ["between", [start_date, end_date]]},
			fields=["holiday_date"],
		)
	}


def _get_overtime_type(
	employee, attendance_date, start_date, end_date, fallback=None, shift_name=None, work_days=None
):
	holiday_dates = _get_employee_holiday_dates(employee, start_date, end_date)
	date_key = str(getdate(attendance_date))
	is_holiday = date_key in holiday_dates

	if is_holiday and frappe.db.exists("Overtime Type", DEFAULT_HOLIDAY_OT_TYPE):
		return DEFAULT_HOLIDAY_OT_TYPE
	if is_rest_day_from_work_days(attendance_date, work_days, shift_name) and frappe.db.exists(
		"Overtime Type", DEFAULT_REST_DAY_OT_TYPE
	):
		return DEFAULT_REST_DAY_OT_TYPE
	return fallback or DEFAULT_REGULAR_OT_TYPE


@frappe.whitelist()
def fetch_overtime_details(employee, start_date, end_date, current_name=None):
	if not employee:
		frappe.throw(_("Please select an Employee first."))
	if not start_date or not end_date:
		frappe.throw(_("Please set Start Date and End Date first."))

	start_date = getdate(start_date)
	end_date = getdate(end_date)
	if start_date > end_date:
		frappe.throw(_("Start Date cannot be after End Date."))

	duplicate_filters = {
		"employee": employee,
		"start_date": ["<=", end_date],
		"end_date": [">=", start_date],
		"docstatus": ["!=", 2],
	}
	if current_name and not str(current_name).startswith("new-"):
		duplicate_filters["name"] = ["!=", current_name]

	duplicate = frappe.db.get_value("Overtime Slip", duplicate_filters, "name")
	if duplicate:
		frappe.throw(
			_("Overtime Slip {0} already exists for this employee between {1} and {2}.").format(
				frappe.bold(duplicate),
				frappe.bold(start_date),
				frappe.bold(end_date),
			)
		)

	records = frappe.get_all(
		"Attendance",
		filters={
			"employee": employee,
			"attendance_date": ["between", [start_date, end_date]],
			"docstatus": 1,
			"overtime_type": ["!=", ""],
			"actual_overtime_duration": [">", 0],
		},
		fields=[
			"name",
			"attendance_date",
			"shift",
			"overtime_type",
			"actual_overtime_duration",
			"standard_working_hours",
		],
		order_by="attendance_date asc",
		limit_page_length=5000,
	)

	rows = []
	total = 0.0
	overtime_type_cache = {}
	work_days = get_employee_roster_work_days(employee, start_date, end_date)
	for record in records:
		overtime_type = _get_overtime_type(
			employee,
			record.attendance_date,
			start_date,
			end_date,
			record.overtime_type,
			record.shift,
			work_days,
		)
		duration = normalize_overtime_duration(
			record.actual_overtime_duration,
			overtime_type,
			overtime_type_cache,
		)
		if duration <= 0:
			continue
		total += duration
		rows.append(
			{
				"reference_document": record.name,
				"date": record.attendance_date,
				"overtime_type": overtime_type,
				"overtime_duration": duration,
				"raw_overtime_duration": flt(record.actual_overtime_duration),
				"standard_working_hours": flt(record.standard_working_hours) or 8,
			}
		)

	return {
		"rows": rows,
		"total_overtime_duration": flt(total, 2),
		"records": len(records),
		"skipped_below_minimum": len(records) - len(rows),
	}


def _get_salary_component_data(salary_component):
	return (
		frappe.db.get_value(
			"Salary Component",
			salary_component,
			[
				"salary_component_abbr",
				"depends_on_payment_days",
				"do_not_include_in_total",
				"do_not_include_in_accounts",
				"is_tax_applicable",
				"is_flexible_benefit",
				"variable_based_on_taxable_salary",
				"exempted_from_income_tax",
			],
			as_dict=True,
		)
		or {}
	)


def _make_salary_detail_row(salary_component, amount, additional_salary):
	component = _get_salary_component_data(salary_component)
	return {
		"salary_component": salary_component,
		"abbr": component.get("salary_component_abbr"),
		"depends_on_payment_days": component.get("depends_on_payment_days") or 0,
		"do_not_include_in_total": component.get("do_not_include_in_total") or 0,
		"do_not_include_in_accounts": component.get("do_not_include_in_accounts") or 0,
		"is_tax_applicable": component.get("is_tax_applicable") or 0,
		"is_flexible_benefit": component.get("is_flexible_benefit") or 0,
		"variable_based_on_taxable_salary": component.get("variable_based_on_taxable_salary") or 0,
		"exempted_from_income_tax": component.get("exempted_from_income_tax") or 0,
		"default_amount": amount,
		"amount": amount,
		"additional_amount": 0,
		"additional_salary": additional_salary,
	}


def _refresh_draft_salary_slips(overtime_slip, additional_salary_by_component):
	draft_slips = frappe.get_all(
		"Salary Slip",
		filters={
			"employee": overtime_slip.employee,
			"docstatus": 0,
			"start_date": ["<=", overtime_slip.end_date],
			"end_date": [">=", overtime_slip.start_date],
		},
		fields=["name"],
	)
	additional_salary_names = set(additional_salary_by_component.values())

	for salary_slip_row in draft_slips:
		salary_slip = frappe.get_doc("Salary Slip", salary_slip_row.name)
		salary_slip.set(
			"earnings",
			[
				row
				for row in salary_slip.earnings
				if row.additional_salary not in additional_salary_names
			],
		)
		for component, additional_salary in additional_salary_by_component.items():
			amount = frappe.db.get_value("Additional Salary", additional_salary, "amount") or 0
			if flt(amount) <= 0:
				continue
			salary_slip.append(
				"earnings",
				_make_salary_detail_row(component, flt(amount, 2), additional_salary),
			)
		salary_slip.save(ignore_permissions=True)


@frappe.whitelist()
def sync_overtime_additional_salaries(overtime_slip_name):
	overtime_slip = frappe.get_doc("Overtime Slip", overtime_slip_name)
	if overtime_slip.docstatus != 1:
		frappe.throw(_("Overtime Slip must be submitted before syncing Additional Salary."))

	components = {
		component: flt(amount, 2)
		for component, amount in overtime_slip.get_overtime_component_amounts().items()
		if flt(amount, 2) > 0
	}

	existing = frappe.get_all(
		"Additional Salary",
		filters={
			"employee": overtime_slip.employee,
			"ref_doctype": "Overtime Slip",
			"ref_docname": overtime_slip.name,
			"docstatus": 1,
		},
		fields=["name", "salary_component"],
	)
	existing_by_component = {row.salary_component: row.name for row in existing}

	created = []
	updated = []
	additional_salary_by_component = {}
	for component, amount in components.items():
		if component in existing_by_component:
			additional_salary = existing_by_component[component]
			frappe.db.set_value(
				"Additional Salary",
				additional_salary,
				{
					"amount": amount,
					"payroll_date": overtime_slip.end_date,
					"company": overtime_slip.company,
				},
			)
			updated.append(additional_salary)
		else:
			doc = frappe.get_doc(
				{
					"doctype": "Additional Salary",
					"company": overtime_slip.company,
					"employee": overtime_slip.employee,
					"salary_component": component,
					"amount": amount,
					"payroll_date": overtime_slip.end_date,
					"overwrite_salary_structure_amount": 0,
					"ref_doctype": "Overtime Slip",
					"ref_docname": overtime_slip.name,
				}
			)
			doc.insert(ignore_permissions=True)
			doc.submit()
			additional_salary = doc.name
			created.append(additional_salary)
		additional_salary_by_component[component] = additional_salary

	_refresh_draft_salary_slips(overtime_slip, additional_salary_by_component)
	frappe.db.commit()

	return {
		"components": components,
		"created": created,
		"updated": updated,
	}
