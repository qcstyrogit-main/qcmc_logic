import frappe


def execute():
	field = "Vehicle-custom_gps_id_number"
	if frappe.db.exists("Custom Field", field):
		frappe.db.set_value("Custom Field", field, {"read_only": 0, "unique": 1})
		frappe.clear_cache(doctype="Vehicle")
