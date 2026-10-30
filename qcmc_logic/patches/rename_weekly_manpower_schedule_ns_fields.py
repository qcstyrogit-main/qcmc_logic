import frappe


def execute():
	doctype = "Weekly Manpower Schedule Detail"
	if not frappe.db.table_exists(doctype):
		return

	for shift in ("day_shift", "night_shift"):
		old_field = f"{shift}_ns"
		new_field = f"{shift}_ps"
		if frappe.db.has_column(doctype, old_field) and frappe.db.has_column(doctype, new_field):
			frappe.db.sql(
				f"""
				UPDATE `tab{doctype}`
				SET `{new_field}` = COALESCE(`{old_field}`, 0)
				"""
			)
