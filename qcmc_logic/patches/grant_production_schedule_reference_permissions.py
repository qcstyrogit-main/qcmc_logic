import frappe


ROLES = {
	"Production - MC",
	"Production - SMB",
	"Production - STCLA",
	"Plant Manager MC",
	"Plant Manager QC",
}
REFERENCE_DOCTYPES = {
	"Company",
	"Warehouse",
	"Plant Floor",
	"Workstation",
	"Employee",
	"Shift Type",
}


def execute():
	for role in ROLES:
		if not frappe.db.exists("Role", role):
			continue
		for doctype in REFERENCE_DOCTYPES:
			ensure_read_permission(doctype, role)
	for doctype in REFERENCE_DOCTYPES:
		frappe.clear_cache(doctype=doctype)


def ensure_read_permission(doctype, role):
	name = frappe.db.get_value(
		"Custom DocPerm",
		{"parent": doctype, "role": role, "permlevel": 0},
		"name",
	)
	values = {
		"read": 1,
		"select": 1,
		"write": 0,
		"create": 0,
		"delete": 0,
		"submit": 0,
		"cancel": 0,
		"amend": 0,
	}
	if name:
		frappe.db.set_value("Custom DocPerm", name, values, update_modified=False)
		return

	frappe.get_doc(
		{
			"doctype": "Custom DocPerm",
			"parent": doctype,
			"role": role,
			"permlevel": 0,
			**values,
		}
	).insert(ignore_permissions=True)

