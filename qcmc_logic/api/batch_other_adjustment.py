import frappe
from frappe import _
from frappe.utils import flt, getdate, now
from hrms.payroll.doctype.salary_structure_assignment.salary_structure_assignment import (
	get_assigned_salary_structure,
)

from qcmc_logic.api.employee_attendance_schedule import _get_logged_in_employee_filters


PARENT_DOCTYPE = "Batch Other Adjustment Entry"
CHILD_DOCTYPE = "Batch Other Adjustment Detail"


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
		_field("naming_series", "Series", "Select", options="BOA-.YYYY.-.####", default="BOA-.YYYY.-.####"),
		_field("payroll_entry", "Payroll Entry", "Link", options="Payroll Entry", in_list_view=1, in_standard_filter=1),
		_field("company", "Company", "Link", options="Company", reqd=1, in_list_view=1, in_standard_filter=1),
		_field("from_date", "From Date", "Date", reqd=1, in_list_view=1),
		_field("to_date", "To Date", "Date", reqd=1, in_list_view=1),
		_field("payroll_date", "Payroll Date", "Date", reqd=1, in_list_view=1),
		_field("column_break_filters", None, "Column Break"),
		_field("department", "Department", "Link", options="Department", in_standard_filter=1),
		_field("branch", "Branch", "Link", options="Branch", in_standard_filter=1),
		_field("employment_type", "Employment Type", "Select", options="\nRegular\nProbationary"),
		_field("custom_payroll_type", "Payroll Type", "Select", options="\nMonthly\nWeekly"),
		_field("adjustment_section", "Adjustment", "Section Break"),
		_field("salary_component", "Salary Component", "Link", options="Salary Component", reqd=1, in_list_view=1),
		_field("component_type", "Component Type", "Data", read_only=1, fetch_from="salary_component.type"),
		_field("amount", "Default Amount", "Currency", reqd=1),
		_field("column_break_adjustment", None, "Column Break"),
		_field("remarks", "Remarks", "Small Text"),
		_field("summary_section", "Summary", "Section Break"),
		_field("status", "Status", "Select", options="Draft\nFetched\nCreated\nPartly Created", default="Draft", read_only=1, in_list_view=1),
		_field("total_employees", "Employees", "Int", read_only=1),
		_field("created_records", "Created Additional Salary", "Int", read_only=1),
		_field("column_break_summary", None, "Column Break"),
		_field("total_amount", "Total Amount", "Currency", read_only=1),
		_field("skipped_rows", "Skipped Rows", "Int", read_only=1),
		_field("last_created_on", "Last Created On", "Datetime", read_only=1),
		_field("details_section", "Employees", "Section Break"),
		_field("details", "Details", "Table", options=CHILD_DOCTYPE),
	]


def _child_fields():
	return [
		_field("selected", "Select", "Check", default="1", in_list_view=1, columns=1),
		_field("employee", "Employee", "Link", options="Employee", read_only=1, in_list_view=1, columns=2),
		_field("employee_name", "Employee Name", "Data", read_only=1, in_list_view=1, columns=3),
		_field("department", "Department", "Link", options="Department", read_only=1, in_list_view=1, columns=2),
		_field("branch", "Branch", "Link", options="Branch", read_only=1, columns=2),
		_field("amount", "Amount", "Currency", in_list_view=1, columns=2),
		_field("additional_salary", "Additional Salary", "Link", options="Additional Salary", read_only=1, in_list_view=1, columns=2),
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
def install_batch_other_adjustment_doctypes():
	_sync_doctype(CHILD_DOCTYPE, _child_fields(), istable=1)
	_sync_doctype(PARENT_DOCTYPE, _parent_fields(), istable=0)
	frappe.db.commit()
	return {"created": [PARENT_DOCTYPE, CHILD_DOCTYPE]}


@frappe.whitelist()
def install_batch_other_adjustment_client_scripts():
	form_script = _install_client_script(
		"Batch Other Adjustment Entry-Form",
		PARENT_DOCTYPE,
		frappe.get_app_path("qcmc_logic", "public", "js", "batch_other_adjustment_entry.js"),
	)
	payroll_entry_script = _install_client_script(
		"Payroll Entry-Batch Overtime",
		"Payroll Entry",
		frappe.get_app_path("qcmc_logic", "public", "js", "payroll_entry.js"),
	)
	return {"installed": [form_script, payroll_entry_script]}


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


def _validate_component(salary_component):
	if not salary_component:
		frappe.throw(_("Please select a Salary Component."))
	component = frappe.db.get_value(
		"Salary Component",
		salary_component,
		["name", "type", "disabled"],
		as_dict=True,
	)
	if not component:
		frappe.throw(_("Salary Component {0} not found.").format(frappe.bold(salary_component)))
	if component.disabled:
		frappe.throw(_("Salary Component {0} is disabled.").format(frappe.bold(salary_component)))
	if component.type not in ("Earning", "Deduction"):
		frappe.throw(_("Salary Component must be Earning or Deduction."))
	return component


@frappe.whitelist()
def fetch_employees(company, from_date, to_date, payroll_date, salary_component, amount, department=None, branch=None, employment_type=None, custom_payroll_type=None):
	if not company:
		frappe.throw(_("Please select a Company."))
	if not from_date or not to_date or not payroll_date:
		frappe.throw(_("Please set From Date, To Date, and Payroll Date."))
	if flt(amount) <= 0:
		frappe.throw(_("Default Amount must be greater than zero."))

	from_date = _date(from_date)
	to_date = _date(to_date)
	payroll_date = _date(payroll_date)
	if from_date > to_date:
		frappe.throw(_("From Date cannot be after To Date."))
	if not (from_date <= payroll_date <= to_date):
		frappe.msgprint(_("Payroll Date is outside the selected range. Additional Salary can still be created."), indicator="orange")

	_validate_component(salary_component)
	employees = frappe.get_all(
		"Employee",
		filters=_employee_filters(company, department, branch, employment_type, custom_payroll_type),
		fields=["name", "employee_name", "department", "branch"],
		order_by="employee_name asc",
		limit_page_length=50000,
	)

	rows = [
		{
			"selected": 1,
			"employee": employee.name,
			"employee_name": employee.employee_name,
			"department": employee.department,
			"branch": employee.branch,
			"amount": flt(amount),
			"row_status": "Ready",
		}
		for employee in employees
	]
	return {
		"rows": rows,
		"total_employees": len(rows),
		"total_amount": sum(flt(row["amount"]) for row in rows),
	}


def _selected_rows(doc):
	return [
		row
		for row in doc.details
		if row.selected and row.employee and flt(row.amount) > 0 and not row.additional_salary
	]


def _existing_additional_salary(employee, salary_component, payroll_date):
	return frappe.db.exists(
		"Additional Salary",
		{
			"employee": employee,
			"salary_component": salary_component,
			"payroll_date": payroll_date,
			"docstatus": ["!=", 2],
		},
	)


def _get_company_currency(company):
	currency = frappe.db.get_value("Company", company, "default_currency")
	if currency:
		return currency
	return frappe.db.get_default("currency")


def _validate_salary_structure_assignments(doc, rows):
	missing = []
	for employee in sorted({row.employee for row in rows if row.employee}):
		if get_assigned_salary_structure(employee, doc.payroll_date):
			continue
		employee_name = frappe.db.get_value("Employee", employee, "employee_name") or employee
		missing.append(f"{employee} - {employee_name}")

	if missing:
		frappe.throw(
			_("Cannot create Additional Salary because these employees have no active Salary Structure Assignment on {0}:<br><br>{1}").format(
				frappe.bold(doc.payroll_date),
				"<br>".join(frappe.bold(employee) for employee in missing),
			)
		)


@frappe.whitelist()
def create_additional_salaries(batch_name):
	doc = frappe.get_doc(PARENT_DOCTYPE, batch_name)
	if not doc.company or not doc.from_date or not doc.to_date or not doc.payroll_date:
		frappe.throw(_("Company, From Date, To Date, and Payroll Date are required."))
	if flt(doc.amount) <= 0:
		frappe.throw(_("Default Amount must be greater than zero."))
	_validate_component(doc.salary_component)

	rows = _selected_rows(doc)
	if not rows:
		frappe.throw(_("No selected employee rows are ready to create."))

	_validate_salary_structure_assignments(doc, rows)

	currency = _get_company_currency(doc.company)
	created = []
	for row in rows:
		existing = _existing_additional_salary(row.employee, doc.salary_component, doc.payroll_date)
		if existing:
			row.additional_salary = existing
			row.row_status = "Skipped"
			row.error_message = "Additional Salary already exists for this employee, component, and payroll date."
			continue

		try:
			additional_salary = frappe.new_doc("Additional Salary")
			additional_salary.employee = row.employee
			additional_salary.company = doc.company
			additional_salary.payroll_date = doc.payroll_date
			additional_salary.salary_component = doc.salary_component
			additional_salary.currency = currency
			additional_salary.amount = flt(row.amount)
			additional_salary.overwrite_salary_structure_amount = 0
			additional_salary.insert(ignore_permissions=True)
			additional_salary.submit()
			row.additional_salary = additional_salary.name
			row.row_status = "Created"
			row.error_message = ""
			created.append(additional_salary.name)
		except Exception as exc:
			frappe.log_error(frappe.get_traceback(), PARENT_DOCTYPE)
			row.row_status = "Error"
			row.error_message = str(exc)

	created_records = len([row for row in doc.details if row.additional_salary and row.row_status == "Created"])
	skipped_rows = len([row for row in doc.details if row.row_status in ("Error", "Skipped")])
	doc.created_records = created_records
	doc.skipped_rows = skipped_rows
	doc.total_amount = sum(flt(row.amount) for row in doc.details if row.selected)
	doc.status = "Created" if created_records and not skipped_rows else "Partly Created" if created_records else "Fetched"
	doc.last_created_on = now()
	doc.save(ignore_permissions=True)
	if doc.status == "Created" and doc.docstatus == 0:
		doc.submit()
	frappe.db.commit()

	return {
		"created": created,
		"created_records": len(created),
		"skipped_rows": skipped_rows,
	}


def cancel_batch_additional_salaries(doc, method=None):
	cancelled = 0
	failed = []
	for row in doc.details:
		if not row.additional_salary:
			continue
		if not frappe.db.exists("Additional Salary", row.additional_salary):
			continue

		additional_salary = frappe.get_doc("Additional Salary", row.additional_salary)
		if additional_salary.docstatus == 2:
			row.row_status = "Cancelled"
			row.error_message = ""
			continue
		if additional_salary.docstatus != 1:
			continue

		try:
			additional_salary.flags.ignore_links = True
			additional_salary.cancel()
			row.row_status = "Cancelled"
			row.error_message = ""
			cancelled += 1
		except Exception as exc:
			failed.append(f"{row.additional_salary}: {exc}")
			row.row_status = "Error"
			row.error_message = str(exc)

	if failed:
		frappe.throw(
			_("Some Additional Salary records could not be cancelled:<br><br>{0}").format("<br>".join(failed))
		)

	if cancelled:
		frappe.msgprint(
			_("{0} generated Additional Salary record(s) cancelled.").format(cancelled),
			indicator="green",
		)


def allow_batch_additional_salary_cancel(doc, method=None):
	if doc.ref_doctype == PARENT_DOCTYPE:
		doc.flags.ignore_links = True
		return

	batch_detail = frappe.db.get_value(
		CHILD_DOCTYPE,
		{"additional_salary": doc.name, "parenttype": PARENT_DOCTYPE},
		["name", "parent"],
		as_dict=True,
	)
	if batch_detail:
		doc.flags.ignore_links = True


def update_batch_row_on_additional_salary_cancel(doc, method=None):
	batch_details = frappe.get_all(
		CHILD_DOCTYPE,
		filters={"additional_salary": doc.name, "parenttype": PARENT_DOCTYPE},
		fields=["name", "parent"],
	)
	for row in batch_details:
		frappe.db.set_value(
			CHILD_DOCTYPE,
			row.name,
			{
				"row_status": "Cancelled",
				"error_message": "",
			},
			update_modified=False,
		)
