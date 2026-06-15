import frappe
from frappe.utils import getdate, now_datetime, today

from qcmc_logic.api.employee_attendance_schedule import get_cutoff_dates


def _last_pay_day(year, month):
	next_month = getdate(f"{year + 1}-01-01" if month == 12 else f"{year}-{month + 1:02d}-01")
	return frappe.utils.add_days(next_month, -1).day


def get_current_payroll_period_label(base_date=None):
	base = getdate(base_date or today())
	pay_day = 15 if base.day <= 15 else min(30, _last_pay_day(base.year, base.month))
	return f"{base.month}/{pay_day}/{base.year}"


def _get_period_dates(payroll_period):
	if "/" in str(payroll_period):
		month, day, year = [int(part) for part in str(payroll_period).split("/")]
		pay_day = getdate(f"{year}-{month:02d}-{day:02d}")
	else:
		pay_day = getdate(payroll_period)

	if pay_day.day == 15:
		from_date = frappe.utils.add_days(pay_day.replace(day=1), -9)
		to_date = pay_day.replace(day=7)
	else:
		from_date = pay_day.replace(day=8)
		to_date = pay_day.replace(day=22)

	return {
		"from_date": str(from_date),
		"to_date": str(to_date),
		"pay_day": str(pay_day),
	}


def _get_default_company():
	return frappe.defaults.get_user_default("Company") or frappe.db.get_single_value(
		"Global Defaults", "default_company"
	)


def apply_defaults(doc, method=None):
	if not doc.get("company"):
		doc.company = _get_default_company()

	defaulted_payroll_period = False
	if not doc.get("payroll_period"):
		doc.payroll_period = get_current_payroll_period_label()
		defaulted_payroll_period = True

	if defaulted_payroll_period or not doc.get("from_date") or not doc.get("to_date") or not doc.get("pay_day"):
		try:
			dates = _get_period_dates(doc.payroll_period)
		except Exception:
			dates = get_cutoff_dates(base_date=today())

		doc.from_date = dates["from_date"] if defaulted_payroll_period else doc.from_date or dates["from_date"]
		doc.to_date = dates["to_date"] if defaulted_payroll_period else doc.to_date or dates["to_date"]
		doc.pay_day = dates["pay_day"] if defaulted_payroll_period else doc.pay_day or dates["pay_day"]

	if not doc.get("generated_on"):
		doc.generated_on = now_datetime()


@frappe.whitelist()
def ensure_default_record():
	names = frappe.get_all(
		"Employee Attendance Schedule",
		fields=["name"],
		limit=1,
		order_by="creation asc",
		ignore_permissions=True,
	)

	if names:
		doc = frappe.get_doc("Employee Attendance Schedule", names[0].name)
		changed = False
		for fieldname in ("company", "payroll_period", "from_date", "to_date", "pay_day", "generated_on"):
			if not doc.get(fieldname):
				changed = True
				break

		if changed:
			apply_defaults(doc)
			doc.save(ignore_permissions=True)
		return doc.name

	doc = frappe.new_doc("Employee Attendance Schedule")
	apply_defaults(doc)
	doc.insert(ignore_permissions=True)
	return doc.name


def ensure_default_record_after_migrate():
	if frappe.db.exists("DocType", "Employee Attendance Schedule"):
		ensure_default_record()
