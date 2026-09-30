import frappe


def execute():
	indexes = (
		("Mobile Device Session", ["user", "revoked"], "mobile_device_session_user_revoked_idx"),
		("Mobile Device Token", ["device_session", "status"], "mobile_device_token_family_status_idx"),
	)
	for doctype, fields, index_name in indexes:
		if frappe.db.table_exists(doctype):
			frappe.db.add_index(doctype, fields, index_name)
