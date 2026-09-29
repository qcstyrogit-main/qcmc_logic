import frappe


def execute():
    if not frappe.db.exists("DocType", "Daily Job Schedule"):
        return

    doctype = frappe.get_doc("DocType", "Daily Job Schedule")
    permission = next(
        (row for row in doctype.permissions
         if row.role == "Machine Shop Foreman" and not row.get("permlevel")
         and not row.get("if_owner")),
        None,
    )
    if permission is None:
        permission = doctype.append("permissions", {"role": "Machine Shop Foreman"})
    for right in ("read", "write", "create", "delete"):
        permission.set(right, 1)

    doctype.save(ignore_permissions=True)
    frappe.clear_cache(doctype="Daily Job Schedule")
