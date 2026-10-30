import frappe
from frappe.permissions import setup_custom_perms


ROLE = "Invoicing Clerk"
USERS = (
	"invoicing_clerk@qcstyro.com",
	"invoicing_clerk@multiplastcorp.com",
)
SALES_INVOICE_PERMISSION = {
	"read": 1,
	"write": 1,
	"create": 1,
	"delete": 1,
	"submit": 1,
	"cancel": 1,
	"amend": 1,
	"export": 1,
	"import": 1,
	"share": 1,
	"print": 1,
	"email": 1,
	"report": 1,
	"select": 1,
}


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
	ensure_sales_invoice_permission()
	frappe.clear_cache(doctype="Sales Invoice")


def ensure_sales_invoice_permission():
	# Sales Invoice has Custom DocPerm rows, which replace its standard DocPerm
	# set. Preserve the existing permissions before adding this role if needed.
	setup_custom_perms("Sales Invoice")
	filters = {
		"parent": "Sales Invoice",
		"role": ROLE,
		"permlevel": 0,
		"if_owner": 0,
	}
	name = frappe.db.get_value("Custom DocPerm", filters, "name")
	if name:
		frappe.db.set_value("Custom DocPerm", name, SALES_INVOICE_PERMISSION, update_modified=False)
		return

	frappe.get_doc({
		"doctype": "Custom DocPerm",
		"parent": "Sales Invoice",
		"parenttype": "DocType",
		"parentfield": "permissions",
		"role": ROLE,
		"permlevel": 0,
		"if_owner": 0,
		**SALES_INVOICE_PERMISSION,
	}).insert(ignore_permissions=True)
