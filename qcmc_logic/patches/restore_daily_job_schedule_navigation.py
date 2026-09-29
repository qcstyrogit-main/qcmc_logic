import json

import frappe


def execute():
    """Keep the custom schedule accessible in its module's sidebar."""
    if not frappe.db.exists("DocType", "Daily Job Schedule"):
        return
    _ensure_workspace_shortcut()
    if not frappe.db.exists("DocType", "Workspace Sidebar"):
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


def _ensure_workspace_shortcut():
    """Keep a visible entry on sites using Workspace rather than Workspace Sidebar."""
    if not frappe.db.exists("Workspace", "Assets"):
        return
    workspace = frappe.get_doc("Workspace", "Assets")
    shortcut = next(
        (row for row in workspace.shortcuts
         if row.type == "DocType" and row.link_to == "Daily Job Schedule"),
        None,
    )
    changed = False
    if shortcut is None:
        shortcut = workspace.append("shortcuts", {
            "type": "DocType",
            "link_to": "Daily Job Schedule",
            "label": "Daily Job Schedule",
            "doc_view": "List",
        })
        changed = True
    content = json.loads(workspace.content or "[]")
    if not any(block.get("type") == "shortcut"
               and block.get("data", {}).get("shortcut_name") == shortcut.label
               for block in content):
        content.append({
            "id": "daily_job_schedule_shortcut",
            "type": "shortcut",
            "data": {"shortcut_name": shortcut.label, "col": 3},
        })
        workspace.content = json.dumps(content)
        changed = True
    if changed:
        previous_in_fixtures = frappe.flags.in_fixtures
        try:
            frappe.flags.in_fixtures = True
            workspace.save(ignore_permissions=True)
        finally:
            frappe.flags.in_fixtures = previous_in_fixtures
        frappe.clear_cache()
