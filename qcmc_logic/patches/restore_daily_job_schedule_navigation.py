import frappe


def execute():
    """Keep the custom schedule accessible in its module's sidebar."""
    if not frappe.db.exists("DocType", "Daily Job Schedule"):
        return
    if not frappe.db.exists("Workspace Sidebar", "Assets"):
        return

    sidebar = frappe.get_doc("Workspace Sidebar", "Assets")
    if any(
        row.link_type == "DocType" and row.link_to == "Daily Job Schedule"
        for row in sidebar.items
    ):
        return

    sidebar.append(
        "items",
        {
            "type": "Link",
            "label": "Daily Job Schedule",
            "link_type": "DocType",
            "link_to": "Daily Job Schedule",
            "child": 0,
        },
    )
    # This is a site customization, not an export into the ERPNext app.
    previous_in_import = frappe.flags.in_import
    try:
        frappe.flags.in_import = True
        sidebar.save(ignore_permissions=True)
    finally:
        frappe.flags.in_import = previous_in_import
    frappe.clear_cache()
