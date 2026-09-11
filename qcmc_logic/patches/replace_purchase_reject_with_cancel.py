from copy import deepcopy
import frappe

DRAFT_CANCELLED = 'Cancelled Before Submission'
SUBMITTED_CANCELLED = 'Cancelled'


def update_workflow(data):
    data = deepcopy(data)
    for row in data['states']:
        if row['state'] == 'Rejected':
            row.update(state=DRAFT_CANCELLED, update_value=DRAFT_CANCELLED)
    if not any(r['state'] == SUBMITTED_CANCELLED for r in data['states']):
        row = deepcopy(next(r for r in data['states'] if r['state'] == DRAFT_CANCELLED))
        row.pop('name', None)
        row.update(state=SUBMITTED_CANCELLED, update_value=SUBMITTED_CANCELLED, doc_status='2')
        data['states'].append(row)
    for row in data['transitions']:
        if row['action'] == 'Reject':
            row.update(action='Cancel', next_state=DRAFT_CANCELLED)
    for state in ('To Receive', 'Received', 'Submitted'):
        if not any(r['state'] == state and r['action'] == 'Cancel' and r['allowed'] == 'Purchase User' for r in data['transitions']):
            row = deepcopy(next(r for r in data['transitions'] if r['action'] == 'Cancel'))
            row.pop('name', None)
            row.update(state=state, allowed='Purchase User', condition='doc.material_request_type == "Purchase"',
                       next_state=SUBMITTED_CANCELLED if state == 'Submitted' else DRAFT_CANCELLED)
            data['transitions'].append(row)
    return data


def execute():
    for state in (DRAFT_CANCELLED, SUBMITTED_CANCELLED):
        if not frappe.db.exists('Workflow State', state):
            frappe.get_doc(dict(doctype='Workflow State', workflow_state_name=state, style='Danger')).insert(ignore_permissions=True)
    if not frappe.db.exists('Workflow Action Master', 'Cancel'):
        frappe.get_doc(dict(doctype='Workflow Action Master', workflow_action_name='Cancel')).insert(ignore_permissions=True)
    w = frappe.get_doc('Workflow', 'Purchase Request')
    data = update_workflow(w.as_dict())
    if data != w.as_dict():
        w.set('states', data['states']); w.set('transitions', data['transitions'])
        w.save(ignore_permissions=True)
    frappe.db.sql('UPDATE `tabMaterial Request` SET workflow_state=%s WHERE material_request_type=%s AND workflow_state=%s AND docstatus=0',
                  (DRAFT_CANCELLED, 'Purchase', 'Rejected'))
    frappe.clear_cache()
