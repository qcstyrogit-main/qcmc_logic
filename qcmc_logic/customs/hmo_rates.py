import frappe
from frappe.utils import flt


def validate_employee_rate(doc, method=None):
	apply_employee_rate_formulas(doc)


def validate_dependent_rate(doc, method=None):
	apply_dependent_rate_formulas(doc)


def validate_rate_plan(doc, method=None):
	for row in doc.get("employee_rates", []):
		apply_employee_rate_formulas(row)
	for row in doc.get("dependent_rates", []):
		apply_dependent_rate_formulas(row)
	validate_external_members(doc)


def validate_external_members(doc):
	rows = doc.get("external_members", [])
	principal_names = {row.member_name for row in rows if row.is_active and row.member_type == "Principal"}
	principal_rates = {
		f"{row.level}-{int(row.mbl)}": row for row in doc.get("employee_rates", []) if row.is_active
	}
	dependent_rates = {
		f"Dependent-{int(row.mbl)}": row for row in doc.get("dependent_rates", []) if row.is_active
	}

	for row in rows:
		if not row.is_active:
			continue
		if row.member_type == "Dependent":
			if row.principal_name not in principal_names:
				frappe.throw(
					f"External HMO member row {row.idx}: principal {row.principal_name!r} was not found."
				)
			if row.rate_code not in dependent_rates:
				frappe.throw(f"External HMO member row {row.idx}: invalid dependent rate {row.rate_code!r}.")
			row.level = None
			row.mbl = dependent_rates[row.rate_code].mbl
		elif row.rate_code not in principal_rates:
			frappe.throw(f"External HMO member row {row.idx}: invalid principal rate {row.rate_code!r}.")
		else:
			row.level = principal_rates[row.rate_code].level
			row.mbl = principal_rates[row.rate_code].mbl


def apply_employee_rate_formulas(doc, has_weekly_cutoff=None):
	total_fee = flt(doc.total_fee)
	er_share = flt(doc.er_share)
	ee_share = flt(total_fee - er_share, 9)
	er_share_month = flt(er_share / 3, 9)
	ee_share_month = flt(ee_share / 3, 9)

	doc.ee_share = ee_share
	doc.er_share_month = er_share_month
	doc.ee_share_month = ee_share_month
	doc.premium = flt(er_share_month + ee_share_month, 9)
	doc.er_share_monthly_cutoff = flt(er_share_month / 2, 9)
	doc.ee_share_monthly_cutoff = flt(ee_share_month / 2, 9)

	if has_weekly_cutoff is None:
		has_weekly_cutoff = bool(flt(doc.er_share_weekly_cutoff) or flt(doc.ee_share_weekly_cutoff))

	doc.er_share_weekly_cutoff = flt(er_share_month / 4, 9) if has_weekly_cutoff else 0
	doc.ee_share_weekly_cutoff = flt(ee_share_month / 4, 9) if has_weekly_cutoff else 0


def apply_dependent_rate_formulas(doc, has_weekly_cutoff=None):
	ee_share_monthly = flt(flt(doc.ee_share) / 3, 9)
	doc.ee_share_monthly = ee_share_monthly
	doc.ee_share_cutoff = flt(ee_share_monthly / 2, 9)

	if has_weekly_cutoff is None:
		has_weekly_cutoff = bool(flt(doc.ee_share_weekly))

	doc.ee_share_weekly = flt(ee_share_monthly / 4, 9) if has_weekly_cutoff else 0
