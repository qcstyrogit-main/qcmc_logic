"""Add conditional evaluations without moving existing Purchase requests."""
from copy import deepcopy

import frappe
from qcmc_logic.customs.purchase_request_evaluation import ASSET, NETWORK, EVALUATORS, MANAGERS

FIELDS = [
    dict(fieldname='custom_pr_evaluation_required', label='Required PR Evaluation', fieldtype='Data',
         insert_after='custom_request_type', read_only=1, no_copy=1),
    dict(fieldname='custom_pr_evaluated_by', label='PR Evaluated By', fieldtype='Link', options='User',
         insert_after='custom_pr_evaluation_required', read_only=1, no_copy=1),
    dict(fieldname='custom_pr_evaluated_on', label='PR Evaluated On', fieldtype='Datetime',
         insert_after='custom_pr_evaluated_by', read_only=1, no_copy=1),
]


def update_workflow(data):
    data = deepcopy(data)
    for state, role in EVALUATORS.items():
        if not any(row['state'] == state for row in data['states']):
            row = deepcopy(next(row for row in data['states'] if row['state'] == 'Pending MIS Supervisor Approval'))
            row.pop('name', None)
            row.update(state=state, allow_edit=role, update_value=state)
            data['states'].append(row)

    transitions = []
    for row in data['transitions']:
        if row['action'] == 'Approve' and row['next_state'] == 'To Receive' and row['state'] in MANAGERS | {'Pending Approval'}:
            # Existing transformed fallback rows must not be split a second time.
            if 'doc.custom_request_type' in (row.get('condition') or ''):
                transitions.append(row)
                continue
            condition = row.get('condition') or 'True'
            types = [('MIS', NETWORK)]
            if row['state'] in MANAGERS:
                types.append(('Office Supplies & Equipment', ASSET))
            for request_type, target in types:
                branch = deepcopy(row)
                branch.pop('name', None)
                branch.update(next_state=target, condition=f'({condition}) and doc.custom_request_type == {request_type!r}')
                transitions.append(branch)
            row['condition'] = f'({condition}) and doc.custom_request_type not in {tuple(t for t, _ in types)!r}'
        transitions.append(row)
    data['transitions'] = transitions

    for state, role in EVALUATORS.items():
        for action, target in [('Approve', 'To Receive'), ('Cancel', 'Cancelled Before Submission')]:
            if any(row['state'] == state and row['action'] == action for row in transitions):
                continue
            source = next(row for row in transitions if row['state'] == 'Pending MIS Supervisor Approval' and row['action'] == action)
            row = deepcopy(source)
            row.pop('name', None)
            request_type = 'MIS' if state == NETWORK else 'Office Supplies & Equipment'
            row.update(state=state, allowed=role, next_state=target,
                       condition=f'doc.material_request_type == "Purchase" and doc.custom_request_type == {request_type!r}')
            transitions.append(row)
    return data


def execute():
    from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

    create_custom_fields({'Material Request': FIELDS})
    for state in EVALUATORS:
        if not frappe.db.exists('Workflow State', state):
            frappe.get_doc(dict(doctype='Workflow State', workflow_state_name=state, style='Warning')).insert(ignore_permissions=True)
    workflow = frappe.get_doc('Workflow', 'Purchase Request')
    data = update_workflow(workflow.as_dict())
    if data != workflow.as_dict():
        workflow.set('states', data['states'])
        workflow.set('transitions', data['transitions'])
        workflow.save(ignore_permissions=True)
    frappe.clear_cache(doctype='Material Request')
    frappe.cache.hdel('workflow', 'Material Request')
