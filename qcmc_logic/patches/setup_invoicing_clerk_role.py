import frappe


ROLE = "Invoicing Clerk"
USERS = (
	"invoicing_clerk@qcstyro.com",
	"invoicing_clerk@multiplastcorp.com",
)


def execute():
	if not frappe.db.exists("Role", ROLE):
		frappe.get_doc({
			"doctype": "Role",
			"role_name": ROLE,
			"desk_access": 1,
			"is_custom": 1,
		}).insert(ignore_permissions=True)
	for user in USERS:
		if frappe.db.exists("User", user):
			frappe.get_doc("User", user).add_roles(ROLE)
