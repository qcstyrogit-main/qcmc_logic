import frappe

from qcmc_logic.customs.payroll_role_scope import PAYROLL_ROLE_RULES


def execute():
	roles = sorted({rule["role"] for rule in PAYROLL_ROLE_RULES})
	changed = False

	for role in roles:
		if not frappe.db.exists("Role", role):
			continue

		frappe.db.delete(
			"Custom DocPerm",
			{"parent": "Overtime Types", "role": role, "permlevel": 0},
		)

		existing = frappe.db.get_value(
			"DocPerm",
			{"parent": "Overtime Types", "role": role, "permlevel": 0},
			"name",
		)
		if existing:
			values = frappe.db.get_value(
				"DocPerm",
				existing,
				["read", "select", "write", "create", "delete"],
				as_dict=True,
			)
			if (
				not values.read
				or not values.select
				or values.write
				or values.create
				or values.delete
			):
				frappe.db.set_value(
					"DocPerm",
					existing,
					{"read": 1, "select": 1, "write": 0, "create": 0, "delete": 0},
					update_modified=False,
				)
				changed = True
			continue

		frappe.get_doc(
			{
				"doctype": "DocPerm",
				"parent": "Overtime Types",
				"parenttype": "DocType",
				"parentfield": "permissions",
				"role": role,
				"permlevel": 0,
				"read": 1,
				"select": 1,
				"write": 0,
				"create": 0,
				"delete": 0,
				"submit": 0,
				"cancel": 0,
				"amend": 0,
				"report": 0,
				"export": 0,
				"import": 0,
				"share": 0,
				"print": 0,
				"email": 0,
			}
		).insert(ignore_permissions=True)
		changed = True

	if changed:
		frappe.clear_cache(doctype="Overtime Types")
