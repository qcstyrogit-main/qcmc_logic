"""Restore the registered, idempotent MC PPIC migration entry point."""
from copy import deepcopy
import frappe
from qcmc_logic.customs.mc_purchase_request import REQUESTER, SUPERVISOR, STATE, MANAGER, CREATOR_FLAG, APPROVED_BY, APPROVED_ON

FIELDS = [
    dict(fieldname=CREATOR_FLAG,label='MC RMFS PR Creator',fieldtype='Check',default='0',hidden=1,
         read_only=1,no_copy=1,insert_after='custom_pr_provincial_creator'),
    dict(fieldname=APPROVED_BY,label='MC PPIC Approved By',fieldtype='Link',options='User',read_only=1,no_copy=1,insert_after=CREATOR_FLAG),
    dict(fieldname=APPROVED_ON,label='MC PPIC Approved On',fieldtype='Datetime',read_only=1,no_copy=1,insert_after=APPROVED_BY),
]
PERMISSIONS = [
    dict(name='qcmc-mc-rmfs-pr-owner',role=REQUESTER,read=1,write=1,create=1,print=1,if_owner=1,permlevel=0),
    dict(name='qcmc-mc-ppic-pr-approver',role=SUPERVISOR,read=1,write=1,print=1,if_owner=0,permlevel=0),
]
ELIGIBLE = "(doc.material_request_type == 'Purchase' and doc.custom_pr_mc_rmfs_creator == 1 and doc.company != 'QC Styropackaging Corporation' and not (doc.custom_pr_provincial_creator == 1 and doc.custom_request_type in ('MIS', 'Office Supplies & Equipment', 'Motorpool')))"


def update_workflow(data):
    data=deepcopy(data)
    for state,role,template in [('Draft',REQUESTER,'Draft'),(STATE,SUPERVISOR,'Pending PPIC Supervisor')]:
        if not any(r['state']==state and r['allow_edit']==role for r in data['states']):
            row=deepcopy(next(r for r in data['states'] if r['state']==template));row.pop('name',None)
            row.update(state=state,allow_edit=role,update_value=state,workflow_builder_id=None);data['states'].append(row)
    for row in data['transitions']:
        if row['state']=='Draft' and row['allowed']!=REQUESTER and CREATOR_FLAG not in (row.get('condition') or ''):
            row['condition']=f"({row.get('condition') or 'True'}) and not {ELIGIBLE}"
    for source,action,target,role,condition in [
        ('Draft','Submit for MC PPIC Approval',STATE,REQUESTER,f'{ELIGIBLE} and doc.owner == frappe.session.user'),
        (STATE,'Approve',MANAGER,SUPERVISOR,ELIGIBLE),
        (STATE,'Cancel','Cancelled Before Submission',SUPERVISOR,ELIGIBLE),
    ]:
        if any(r['state']==source and r['action']==action and r['next_state']==target and r['allowed']==role for r in data['transitions']):continue
        row=deepcopy(next(r for r in data['transitions'] if r['action']=='Approve'));row.pop('name',None)
        row.update(state=source,action=action,next_state=target,allowed=role,condition=condition,workflow_builder_id=None)
        data['transitions'].append(row)
    return data


def execute():
    from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

    if not frappe.db.exists('Role',SUPERVISOR):
        frappe.get_doc(dict(doctype='Role',role_name=SUPERVISOR,desk_access=1,is_custom=1)).insert(ignore_permissions=True)
    create_custom_fields({'Material Request':FIELDS})
    if not frappe.db.exists('Workflow State',STATE):
        frappe.get_doc(dict(doctype='Workflow State',workflow_state_name=STATE,style='Warning')).insert(ignore_permissions=True)
    action='Submit for MC PPIC Approval'
    if not frappe.db.exists('Workflow Action Master',action):
        frappe.get_doc(dict(doctype='Workflow Action Master',workflow_action_name=action)).insert(ignore_permissions=True)
    for permission in PERMISSIONS:
        if not frappe.db.exists('Custom DocPerm',{'parent':'Material Request','role':permission['role'],'permlevel':0}):
            frappe.get_doc(dict(doctype='Custom DocPerm',parent='Material Request',**permission)).insert(ignore_permissions=True,set_name=permission['name'])
    user=frappe.get_doc('User','mcppic@qcedsa.local')
    if SUPERVISOR not in [r.role for r in user.roles]:user.add_roles(SUPERVISOR)
    workflow=frappe.get_doc('Workflow','Purchase Request');data=update_workflow(workflow.as_dict())
    if data!=workflow.as_dict():
        workflow.set('states',data['states']);workflow.set('transitions',data['transitions']);workflow.save(ignore_permissions=True)
    frappe.clear_cache()
