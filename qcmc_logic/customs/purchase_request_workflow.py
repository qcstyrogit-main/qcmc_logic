"""Reason capture and server-side safeguards for Purchase request decisions."""
import frappe
from frappe.utils import escape_html

DECISIONS = {'Reject': 'Rejected', 'Return for Correction': 'Draft'}
APPROVAL_STATES = {
    'Pending PPIC Supervisor', 'Pending QC PM Approval', 'Pending MC PM Approval',
    'Pending Logistics Manager Approval', 'Pending Approval',
    'Pending Machine Shop Supervisor Approval', 'Pending MIS Supervisor Approval',
}


@frappe.whitelist()
def apply_workflow(doc, action):
    from frappe.model.workflow import apply_workflow as standard_apply_workflow

    data = frappe.parse_json(doc) if isinstance(doc, str) else doc
    if data.get('doctype') != 'Material Request' or action not in DECISIONS:
        return standard_apply_workflow(doc, action)
    current = frappe.get_doc('Material Request', data.get('name'))
    current.check_permission('read')
    if current.material_request_type != 'Purchase':
        return standard_apply_workflow(doc, action)
    reason = data.get('_qcmc_workflow_reason')
    if not isinstance(reason, str) or not reason.strip():
        frappe.throw('A reason is required for Reject or Return for Correction.')
    if current.workflow_state not in APPROVAL_STATES:
        frappe.throw('This action is available only while awaiting approval.')
    previous = frappe.flags.qcmc_purchase_decision
    frappe.flags.qcmc_purchase_decision = (current.name, current.workflow_state, DECISIONS[action])
    try:
        result = standard_apply_workflow(doc, action)
        result.add_comment('Comment', text=(
            f'<b>{escape_html(action)}</b> from {escape_html(current.workflow_state)}'
            f'<br>{escape_html(reason.strip())}'
        ))
        return result
    finally:
        frappe.flags.qcmc_purchase_decision = previous


def validate_decision(doc):
    if doc.material_request_type != 'Purchase':
        return
    old = doc.get_doc_before_save()
    if not old:
        return
    if old.workflow_state == 'Rejected':
        frappe.throw('Rejected Purchase requests are read-only.')
    if old.workflow_state == 'Draft' and old.owner != frappe.session.user:
        frappe.throw('Only the creator can edit or resubmit a draft Purchase request.')
    if old.workflow_state in APPROVAL_STATES and doc.workflow_state in DECISIONS.values():
        expected = (doc.name, old.workflow_state, doc.workflow_state)
        if frappe.flags.qcmc_purchase_decision != expected:
            frappe.throw('Use Reject or Return for Correction and provide a reason.')
