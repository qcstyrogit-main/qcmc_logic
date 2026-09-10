import frappe


def execute():
    workflow = frappe.get_doc('Workflow', 'Purchase Request')
    invalid = [
        row for row in workflow.transitions
        if row.allowed == 'Stockroom_PR_MC_lv1'
        and row.next_state == 'Pending QC PM Approval'
    ]
    if not invalid:
        return
    for row in invalid:
        workflow.remove(row)
    workflow.save(ignore_permissions=True)
    frappe.clear_cache(doctype='Material Request')
    frappe.cache.hdel('workflow', 'Material Request')
