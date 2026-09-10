import frappe


def execute():
    """Give QC Stockroom requesters the existing RMFS initial approval route."""
    workflow = frappe.get_doc("Workflow", "Purchase Request")
    changed = False
    for table, role_field in (("states", "allow_edit"), ("transitions", "allowed")):
        sources = [
            row for row in workflow.get(table)
            if row.get(role_field) == "RMFS_PR_QC_lv1"
        ]
        if not sources:
            frappe.throw(f"Purchase Request has no RMFS_PR_QC_lv1 {table} to copy")
        for source in sources:
            values = {
                field.fieldname: source.get(field.fieldname)
                for field in source.meta.fields
                if field.fieldtype not in ("Section Break", "Column Break", "Tab Break")
            }
            values[role_field] = "Stockroom_PR_QC_lv1"
            values["workflow_builder_id"] = None
            if any(
                all(row.get(key) == value for key, value in values.items())
                for row in workflow.get(table)
            ):
                continue
            workflow.append(table, values)
            changed = True
    if changed:
        # Older sites can have transitions whose action master is missing.
        # Restore those existing labels so normal link validation can run.
        for transition in workflow.transitions:
            if not frappe.db.exists("Workflow Action Master", transition.action):
                frappe.get_doc({
                    "doctype": "Workflow Action Master",
                    "workflow_action_name": transition.action,
                }).insert(ignore_permissions=True)
        workflow.save(ignore_permissions=True)
        frappe.clear_cache(doctype="Material Request")
        frappe.cache.hdel("workflow", "Material Request")
