from copy import deepcopy

import frappe

from qcmc_logic.customs.purchase_request_workflow import APPROVAL_STATES, DECISIONS


def extend_workflow(data):
    data = deepcopy(data)
    if not any(row['state'] == 'Rejected' for row in data['states']):
        row = deepcopy(next(row for row in data['states'] if row['state'] == 'To Receive'))
        row.pop('name', None)
        row.update(state='Rejected', update_value='Rejected', is_optional_state=1,
                   workflow_builder_id=None)
        data['states'].append(row)
    groups = {}
    for row in data['transitions']:
        if row['state'] in APPROVAL_STATES and row['action'] not in DECISIONS:
            groups.setdefault((row['state'], row['allowed']), []).append(row)
    for (state, role), rows in groups.items():
        for action, target in DECISIONS.items():
            if any(r['state'] == state and r['allowed'] == role and r['action'] == action
                   for r in data['transitions']):
                continue
            row = deepcopy(rows[0])
            row.pop('name', None)
            row.update(action=action, next_state=target, workflow_builder_id=None,
                       transition_tasks=None,
                       condition=' or '.join(f'({r.get("condition") or "True"})' for r in rows))
            data['transitions'].append(row)
    return data


def execute():
    if not frappe.db.exists('Workflow State', 'Rejected'):
        frappe.get_doc({'doctype': 'Workflow State', 'workflow_state_name': 'Rejected',
                        'style': 'Danger'}).insert(ignore_permissions=True)
    for action in DECISIONS:
        if not frappe.db.exists('Workflow Action Master', action):
            frappe.get_doc({'doctype': 'Workflow Action Master',
                            'workflow_action_name': action}).insert(ignore_permissions=True)
    workflow = frappe.get_doc('Workflow', 'Purchase Request')
    data = extend_workflow(workflow.as_dict())
    if len(data['states']) != len(workflow.states) or len(data['transitions']) != len(workflow.transitions):
        workflow.set('states', data['states'])
        workflow.set('transitions', data['transitions'])
        workflow.save(ignore_permissions=True)
    frappe.clear_cache()
