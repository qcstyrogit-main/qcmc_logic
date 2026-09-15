import frappe


def execute():
    workflow = frappe.get_doc('Workflow', 'Purchase Request')
    rows = [row for row in workflow.transitions if row.action == 'Return for Correction']
    if rows:
        for row in rows:
            workflow.remove(row)
        workflow.save(ignore_permissions=True)
    frappe.clear_cache()
    frappe.cache.hdel('workflow', 'Material Request')
