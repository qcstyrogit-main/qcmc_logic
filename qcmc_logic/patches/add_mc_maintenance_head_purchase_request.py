"""Insert Maintenance Head only into the existing Stockroom MC Draft route."""
from copy import deepcopy
import frappe
from qcmc_logic.customs.mc_maintenance_purchase_request import ROLE, STATE, REQUESTER, REQUIRED, APPROVED_BY, APPROVED_ON
from qcmc_logic.customs.mc_purchase_request import MANAGER

ACTION = 'Submit for MC Maintenance Approval'
FIELDS = [
    dict(fieldname=REQUIRED, label='MC Maintenance Approval Required', fieldtype='Check', default='0',
         hidden=1, read_only=1, no_copy=1, insert_after='custom_pr_mc_ppic_approved_on'),
    dict(fieldname=APPROVED_BY, label='MC Maintenance Approved By', fieldtype='Link', options='User',
         read_only=1, no_copy=1, insert_after=REQUIRED),
    dict(fieldname=APPROVED_ON, label='MC Maintenance Approved On', fieldtype='Datetime',
         read_only=1, no_copy=1, insert_after=APPROVED_BY),
]
PERMISSION = dict(name='qcmc-mc-maintenance-pr-head', role=ROLE, permlevel=0, read=1, write=1, print=1, if_owner=0)
ROLE_PROFILE = 'PR - MC Maintenance Head'


def assign_approver(approver):
    user=frappe.get_doc('User',approver)
    if user.get('role_profiles'):
        if not frappe.db.exists('Role Profile',ROLE_PROFILE):
            frappe.get_doc(dict(doctype='Role Profile',role_profile=ROLE_PROFILE,roles=[{'role':ROLE}])).insert(ignore_permissions=True)
        profile=frappe.get_doc('Role Profile',ROLE_PROFILE)
        if {r.role for r in profile.roles}!={ROLE}:
            frappe.throw('The MC Maintenance Head profile must contain only the designated approval role.')
        if ROLE_PROFILE not in [row.role_profile for row in user.role_profiles]:
            user.append('role_profiles',{'role_profile':ROLE_PROFILE})
            user.save(ignore_permissions=True)
    elif ROLE not in [row.role for row in user.roles]:
        user.add_roles(ROLE)


def update_workflow(data):
    data = deepcopy(data)
    if not any(row['state'] == STATE for row in data['states']):
        row=deepcopy(next(row for row in data['states'] if row['state']=='Pending MC PPIC Supervisor'))
        row.pop('name',None)
        row.update(state=STATE,allow_edit=ROLE,update_value=STATE,workflow_builder_id=None)
        data['states'].append(row)
    for row in data['transitions']:
        if row['state']=='Draft' and row['allowed']==REQUESTER and row['next_state']==MANAGER:
            row.update(action=ACTION,next_state=STATE)
    for action,target in [('Approve',MANAGER),('Cancel','Cancelled Before Submission')]:
        if any(row['state']==STATE and row['action']==action for row in data['transitions']):
            continue
        row=deepcopy(next(row for row in data['transitions'] if row['state']=='Pending MC PPIC Supervisor' and row['action']==action))
        row.pop('name',None)
        row.update(state=STATE,allowed=ROLE,next_state=target,workflow_builder_id=None,
                   condition="doc.material_request_type == 'Purchase' and doc.custom_pr_mc_maintenance_required == 1")
        data['transitions'].append(row)
    return data


def execute(approver=None):
    from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

    if not frappe.db.exists('Role',ROLE):
        frappe.get_doc(dict(doctype='Role',role_name=ROLE,desk_access=1,is_custom=1)).insert(ignore_permissions=True)
    create_custom_fields({'Material Request':FIELDS})
    if not frappe.db.exists('Workflow State',STATE):
        frappe.get_doc(dict(doctype='Workflow State',workflow_state_name=STATE,style='Warning')).insert(ignore_permissions=True)
    if not frappe.db.exists('Workflow Action Master',ACTION):
        frappe.get_doc(dict(doctype='Workflow Action Master',workflow_action_name=ACTION)).insert(ignore_permissions=True)
    if not frappe.db.exists('Custom DocPerm',{'parent':'Material Request','role':ROLE,'permlevel':0}):
        frappe.get_doc(dict(doctype='Custom DocPerm',parent='Material Request',**PERMISSION)).insert(
            ignore_permissions=True,set_name=PERMISSION['name'])
    if approver:
        assign_approver(approver)
    workflow=frappe.get_doc('Workflow','Purchase Request')
    data=update_workflow(workflow.as_dict())
    if data!=workflow.as_dict():
        workflow.set('states',data['states'])
        workflow.set('transitions',data['transitions'])
        workflow.save(ignore_permissions=True)
    frappe.clear_cache()
