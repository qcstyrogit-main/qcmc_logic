"""Add creator-based provincial Draft routing without reclassifying old requests."""
from copy import deepcopy

import frappe
from qcmc_logic.customs.provincial_purchase_request import CREATOR, PROVINCIAL, ROLE, LOGISTICS
from qcmc_logic.customs.purchase_request_evaluation import NETWORK, ASSET

ACTION = 'Submit for Approval'
ROUTES = {'MIS': NETWORK, 'Office Supplies & Equipment': ASSET, 'Motorpool': LOGISTICS}
FIELDS = [
    dict(fieldname=CREATOR, label='Original PR Creator', fieldtype='Link', options='User',
         read_only=1, no_copy=1, insert_after='custom_request_type'),
    dict(fieldname=PROVINCIAL, label='Provincial PR Creator', fieldtype='Check',
         read_only=1, no_copy=1, default='0', insert_after=CREATOR),
]
PERMISSION = dict(role=ROLE, permlevel=0, read=1, write=1, create=1, print=1, if_owner=1)
EXCLUSION = "not (doc.material_request_type == 'Purchase' and doc.custom_pr_provincial_creator == 1 and doc.custom_request_type in ('MIS', 'Office Supplies & Equipment', 'Motorpool'))"


def update_workflow(data):
    data = deepcopy(data)
    if not any(row['state'] == 'Draft' and row['allow_edit'] == ROLE for row in data['states']):
        row = deepcopy(next(row for row in data['states'] if row['state'] == 'Draft'))
        row.pop('name', None)
        row.update(allow_edit=ROLE, workflow_builder_id=None)
        data['states'].append(row)
    for row in data['transitions']:
        if row['state'] == 'Draft' and row['allowed'] != ROLE and PROVINCIAL not in (row.get('condition') or ''):
            condition = row.get('condition') or 'True'
            row['condition'] = f'({condition}) and {EXCLUSION}'
    for request_type, destination in ROUTES.items():
        if any(row['state'] == 'Draft' and row['allowed'] == ROLE and row['next_state'] == destination for row in data['transitions']):
            continue
        row = deepcopy(next(row for row in data['transitions'] if row['state'] == 'Draft'))
        row.pop('name', None)
        row.update(action=ACTION, allowed=ROLE, next_state=destination, workflow_builder_id=None,
                   condition=f'doc.material_request_type == "Purchase" and doc.custom_pr_provincial_creator == 1 and doc.custom_request_type == {request_type!r} and doc.custom_pr_original_creator == frappe.session.user')
        data['transitions'].append(row)
    return data


def execute():
    from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

    if not frappe.db.exists('Role', ROLE):
        frappe.throw('Provincial Stock User role must exist before configuring PR routing.')
    create_custom_fields({'Material Request': FIELDS})
    if not frappe.db.exists('Workflow Action Master', ACTION):
        frappe.get_doc(dict(doctype='Workflow Action Master', workflow_action_name=ACTION)).insert(ignore_permissions=True)
    workflow = frappe.get_doc('Workflow', 'Purchase Request')
    data = update_workflow(workflow.as_dict())
    if data != workflow.as_dict():
        workflow.set('states', data['states'])
        workflow.set('transitions', data['transitions'])
        workflow.save(ignore_permissions=True)
    # Add only the creator-scoped grants needed for draft requests; controller
    # permissions prevent these grants from applying to non-Purchase documents.
    if not frappe.db.exists('Custom DocPerm', {'parent': 'Material Request', 'role': ROLE, 'permlevel': 0}):
        frappe.get_doc(dict(doctype='Custom DocPerm', name='qcmc-provincial-pr-owner', parent='Material Request',
                            parenttype='DocType', parentfield='permissions', **PERMISSION)).insert(
                                ignore_permissions=True, set_name='qcmc-provincial-pr-owner')
    frappe.clear_cache(doctype='Material Request')
    frappe.cache.hdel('workflow', 'Material Request')
