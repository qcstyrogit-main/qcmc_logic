from copy import deepcopy

import frappe

QC_COMPANY = "QC Styropackaging Corporation"
OLD_STATE = "Pending PM Approval"
QC_STATE = "Pending QC PM Approval"
MC_STATE = "Pending MC PM Approval"


def split_workflow(data):
    """Split PM states and route each existing incoming path by company."""
    data = deepcopy(data)
    for row in data['states']:
        if row['state'] == OLD_STATE:
            row['state'] = QC_STATE if row['allow_edit'] == 'Plant Manager QC' else MC_STATE
            if row.get('update_value') == OLD_STATE:
                row['update_value'] = row['state']
    transitions = []
    for row in data['transitions']:
        if row['next_state'] == OLD_STATE:
            for state, operator, action in (
                (QC_STATE, '==', 'Submit for QC Plant Manager Approval'),
                (MC_STATE, '!=', 'Submit for MC Approval'),
            ):
                new = deepcopy(row)
                new.pop('name', None)
                new['next_state'] = state
                new['action'] = action
                new['condition'] = f'({row.get("condition") or "True"}) and doc.company {operator} "{QC_COMPANY}"'
                new['workflow_builder_id'] = None
                transitions.append(new)
        elif row['state'] == OLD_STATE:
            qc = row['allowed'] == 'Plant Manager QC'
            row['state'] = QC_STATE if qc else MC_STATE
            operator = '==' if qc else '!='
            row['condition'] = f'({row.get("condition") or "True"}) and doc.company {operator} "{QC_COMPANY}"'
            transitions.append(row)
        else:
            transitions.append(row)
    data['transitions'] = transitions
    return data


def update_approval_script(script):
    return script.replace(
        'frm.doc.workflow_state === "Pending PM Approval"',
        '(frm.doc.workflow_state === "Pending QC PM Approval" || '
        'frm.doc.workflow_state === "Pending MC PM Approval")',
    )


def execute():
    for state in (QC_STATE, MC_STATE):
        if not frappe.db.exists('Workflow State', state):
            frappe.get_doc({'doctype': 'Workflow State', 'workflow_state_name': state}).insert(ignore_permissions=True)
    workflow = frappe.get_doc('Workflow', 'Purchase Request')
    if any(row.state == OLD_STATE for row in workflow.states):
        data = split_workflow(workflow.as_dict())
        workflow.set('states', data['states'])
        workflow.set('transitions', data['transitions'])
        workflow.save(ignore_permissions=True)
    # Metadata migration only: preserve docstatus and all business fields.
    frappe.db.sql(
        '''UPDATE `tabMaterial Request`
           SET workflow_state = CASE WHEN company = %s THEN %s ELSE %s END
           WHERE workflow_state = %s''',
        (QC_COMPANY, QC_STATE, MC_STATE, OLD_STATE),
    )
    if frappe.db.exists('Client Script', 'PR_Approval'):
        script = frappe.get_doc('Client Script', 'PR_Approval')
        updated = update_approval_script(script.script or '')
        if updated != script.script:
            script.script = updated
            script.save(ignore_permissions=True)
    frappe.clear_cache(doctype='Material Request')
    frappe.cache.hdel('workflow', 'Material Request')
