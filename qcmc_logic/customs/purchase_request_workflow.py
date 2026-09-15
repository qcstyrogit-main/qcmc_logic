"""Reason capture and server-side safeguards for Purchase request decisions."""
import frappe
from frappe.utils import escape_html

DECISIONS = {'Cancel': 'Cancelled Before Submission'}
TERMINAL_STATES = {'Rejected', 'Cancelled Before Submission', 'Cancelled'}
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
        frappe.throw('A reason is required for Cancel.')
    if current.workflow_state not in APPROVAL_STATES | {'To Receive', 'Received', 'Submitted'}:
        frappe.throw('Cancellation is not available at this workflow state.')
    if current.workflow_state == 'Submitted' and current.docstatus != 1:
        frappe.throw('This request is marked Submitted but is still a draft internally. Its status must be repaired before cancellation.')
    target = 'Cancelled' if current.docstatus == 1 else 'Cancelled Before Submission'
    previous = frappe.flags.qcmc_purchase_decision
    frappe.flags.qcmc_purchase_decision = (current.name, current.workflow_state, target)
    try:
        result = standard_apply_workflow(doc, action)
        # ERPNext leaves pre-submission documents at Draft during validation.
        # Their business status must still reflect the completed cancellation.
        result.db_set('status', 'Cancelled', update_modified=False)
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
    if old.workflow_state in TERMINAL_STATES:
        frappe.throw('Cancelled Purchase requests are read-only.')
    if old.workflow_state == 'Draft' and old.owner != frappe.session.user:
        frappe.throw('Only the creator can edit or resubmit a draft Purchase request.')
    if doc.workflow_state in TERMINAL_STATES:
        expected = (doc.name, old.workflow_state, doc.workflow_state)
        if frappe.flags.qcmc_purchase_decision != expected:
            frappe.throw('Use Cancel and provide a reason.')
