import frappe


def execute():
	for doctype, filters in (
		("Client Script", {"dt": "Employee Attendance Schedule"}),
		("Property Setter", {"doc_type": "Employee Attendance Schedule"}),
		("Report", {"name": "Employee Attendance Schedule"}),
	):
		for name in frappe.get_all(doctype, filters=filters, pluck="name"):
			frappe.delete_doc(doctype, name, ignore_permissions=True, force=True)

	for doctype in ("Employee Attendance Schedule", "Employee Attendance Schedule Detail"):
		if not frappe.db.exists("DocType", doctype):
			continue

		for name in frappe.get_all(doctype, pluck="name"):
			frappe.delete_doc(doctype, name, ignore_permissions=True, force=True)

		frappe.delete_doc("DocType", doctype, ignore_permissions=True, force=True)

	viewer = frappe.db.exists("Report", "Employee Attendance Viewer")
	if viewer:
		frappe.db.set_value("Report", viewer, "ref_doctype", "Employee", update_modified=False)

	frappe.clear_cache()
