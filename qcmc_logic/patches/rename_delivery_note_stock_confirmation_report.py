import frappe


def execute():
	old_name = "Delivery Note Stock Confirmation"
	new_name = "Delivery Schedule Confirmation"

	if frappe.db.exists("Report", old_name) and not frappe.db.exists("Report", new_name):
		frappe.rename_doc("Report", old_name, new_name, force=True)
	elif frappe.db.exists("Report", old_name) and frappe.db.exists("Report", new_name):
		frappe.delete_doc("Report", old_name, ignore_permissions=True, force=True)

	if frappe.db.exists("Report", new_name):
		report = frappe.get_doc("Report", new_name)
		report.report_name = new_name
		report.module = "QCMC Logics"
		report.ref_doctype = "Delivery Note"
		report.report_type = "Script Report"
		report.is_standard = "Yes"
		existing_roles = {row.role for row in report.roles}
		for role in ("Stock Confirm User", "Sales Coordinator"):
			if role not in existing_roles:
				report.append("roles", {"role": role})
		report.save(ignore_permissions=True)
