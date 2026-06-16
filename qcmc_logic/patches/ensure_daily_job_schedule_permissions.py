import frappe


def execute():
    if not frappe.db.exists("DocType", "Daily Job Schedule"):
        return

    doctype = frappe.get_doc("DocType", "Daily Job Schedule")
    existing_roles = {row.role for row in doctype.permissions}

    if "Machine Shop Foreman" not in existing_roles:
        doctype.append(
            "permissions",
            {
                "role": "Machine Shop Foreman",
                "read": 1,
                "write": 1,
                "create": 1,
                "delete": 1,
            },
        )

    doctype.save(ignore_permissions=True)
    frappe.clear_cache(doctype="Daily Job Schedule")
