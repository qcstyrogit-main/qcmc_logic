import frappe


WEEKLY_BASIC_COMPONENTS = ("Basic Pay", "Weekly Basic Pay")


@frappe.whitelist()
def setup_weekly_basic_pay_component():
	return remove_weekly_basic_pay_setup()


@frappe.whitelist()
def remove_weekly_basic_pay_setup():
	removed_structure_rows = remove_weekly_basic_from_salary_structure()
	updated_salary_slips = remove_weekly_basic_from_draft_salary_slips()
	removed_component = remove_weekly_basic_component()
	frappe.clear_cache()
	frappe.db.commit()
	return {
		"removed_structure_rows": removed_structure_rows,
		"updated_salary_slips": updated_salary_slips,
		"removed_component": removed_component,
	}


def remove_weekly_basic_from_salary_structure():
	if not frappe.db.exists("Salary Structure", "Weekly Employees"):
		return 0

	rows = frappe.get_all(
		"Salary Detail",
		filters={
			"parent": "Weekly Employees",
			"parenttype": "Salary Structure",
			"parentfield": "earnings",
			"salary_component": ["in", WEEKLY_BASIC_COMPONENTS],
		},
		pluck="name",
	)
	for row in rows:
		frappe.delete_doc("Salary Detail", row, force=True, ignore_permissions=True)
	return len(rows)


def remove_weekly_basic_from_draft_salary_slips():
	salary_slips = frappe.get_all(
		"Salary Slip",
		filters={
			"docstatus": 0,
			"salary_structure": "Weekly Employees",
		},
		pluck="name",
	)
	updated_salary_slips = []
	for salary_slip in salary_slips:
		doc = frappe.get_doc("Salary Slip", salary_slip)
		earnings = [
			row
			for row in doc.get("earnings", [])
			if row.salary_component not in WEEKLY_BASIC_COMPONENTS
		]
		if len(earnings) == len(doc.get("earnings", [])):
			continue
		doc.set("earnings", earnings)
		doc.save(ignore_permissions=True)
		updated_salary_slips.append(doc.name)
	return updated_salary_slips


def remove_weekly_basic_component():
	if not frappe.db.exists("Salary Component", "Weekly Basic Pay"):
		return False

	linked_rows = frappe.db.count(
		"Salary Detail",
		{"salary_component": "Weekly Basic Pay"},
	)
	if linked_rows:
		return False

	frappe.delete_doc(
		"Salary Component",
		"Weekly Basic Pay",
		force=True,
		ignore_permissions=True,
	)
	return True
