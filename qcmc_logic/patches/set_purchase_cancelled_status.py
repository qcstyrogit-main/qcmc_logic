import frappe


def execute():
    frappe.db.sql(
        '''UPDATE `tabMaterial Request` SET status='Cancelled'
           WHERE material_request_type='Purchase'
           AND workflow_state IN ('Cancelled Before Submission', 'Cancelled')
           AND COALESCE(status, '') != 'Cancelled' '''
    )
    frappe.clear_cache()
