"""Conditional PR evaluations; legacy and other approval routes stay unchanged."""
import frappe
from frappe.utils import flt, now_datetime

NETWORK = 'Pending Network Admin Evaluation'
ASSET = 'Pending Asset Management Evaluation'
EVALUATORS = {NETWORK: 'Network Admin', ASSET: 'Asset Management User'}
MANAGERS = {
    'Pending QC PM Approval', 'Pending MC PM Approval',
    'Pending Logistics Manager Approval', 'Pending Machine Shop Supervisor Approval',
}
EVIDENCE = ('custom_pr_evaluation_required', 'custom_pr_evaluated_by', 'custom_pr_evaluated_on')
HEADER = ('material_request_type', 'custom_request_type', 'company', 'set_warehouse')
ITEM = ('item_code', 'qty', 'uom', 'conversion_factor', 'warehouse', 'schedule_date', 'description', 'project')
TERMINAL = {'Cancelled Before Submission', 'Cancelled', 'Rejected'}


def required_evaluation(doc, state=None):
    if doc.get('material_request_type') != 'Purchase':
        return None
    state = state or doc.get('workflow_state')
    if state == 'Draft':
        from qcmc_logic.customs.provincial_purchase_request import provincial_destination

        destination = provincial_destination(doc)
        return destination if destination in EVALUATORS else None
    if doc.get('custom_request_type') == 'MIS' and state in MANAGERS | {'Pending Approval'}:
        return NETWORK
    if doc.get('custom_request_type') == 'Office Supplies & Equipment' and state in MANAGERS:
        return ASSET
    return None


def _details(doc):
    # Ignore derived fulfilment quantities, which purchasing updates later.
    return (
        tuple(str(doc.get(key) or '') for key in HEADER),
        [tuple(flt(row.get(key)) if key in {'qty', 'conversion_factor'} else str(row.get(key) or '')
               for key in ITEM) for row in doc.get('items', [])],
    )


def validate_evaluation(doc):
    from qcmc_logic.customs.provincial_purchase_request import validate_provincial_origin, validate_provincial_route

    validate_provincial_origin(doc)
    validate_provincial_route(doc)
    old = doc.get_doc_before_save()
    if not old:
        if any(doc.get(key) for key in EVIDENCE):
            frappe.throw('Evaluation history cannot be supplied on a new request.')
        return
    if any(str(doc.get(key) or '') != str(old.get(key) or '') for key in EVIDENCE):
        frappe.throw('Evaluation history is maintained by the server.')

    required = required_evaluation(old)
    target = doc.get('workflow_state')
    current = old.get('workflow_state')
    tracked = old.get(EVIDENCE[0])
    # Frappe can derive a submitted workflow state after controller validation.
    # Check docstatus too, so direct submit() cannot bypass the pending stage.
    pending = required or current in EVALUATORS or (tracked and not old.get(EVIDENCE[1]))
    if pending and doc.get('docstatus', 0) != 0 and target not in TERMINAL:
        frappe.throw('Complete evaluation before submitting this Purchase request.')
    if (current != 'Draft' or target != current) and (required or required_evaluation(doc, current)) and any(doc.get(key) != old.get(key) for key in HEADER):
        frappe.throw('Request type, company and warehouse cannot change during this approval.')
    if required and target != current and target not in TERMINAL:
        if target != required:
            frappe.throw('This Purchase request must complete the required evaluation.')
        if _details(doc) != _details(old):
            frappe.throw('Save item changes before requesting evaluation.')
        doc.set(EVIDENCE[0], required)
        doc.set(EVIDENCE[1], None)
        doc.set(EVIDENCE[2], None)
    elif target in EVALUATORS and target != current:
        frappe.throw('Evaluation must follow the applicable manager approval.')

    if current in EVALUATORS:
        if tracked != current:
            frappe.throw('This request has invalid evaluation history.')
        if any(doc.get(key) != old.get(key) for key in HEADER):
            frappe.throw('Request type, company and warehouse cannot change during evaluation.')
        if target == 'To Receive':
            if EVALUATORS[current] not in frappe.get_roles():
                frappe.throw('Only the designated evaluator role can approve this request.')
            if _details(doc) != _details(old):
                frappe.throw('Save item changes before approving evaluation.')
            doc.set(EVIDENCE[1], frappe.session.user)
            doc.set(EVIDENCE[2], now_datetime())
        elif target != current and target not in TERMINAL:
            frappe.throw('Evaluation approval must proceed to To Receive.')

    if tracked:
        if old.get(EVIDENCE[1]) and _details(doc) != _details(old):
            frappe.throw('Evaluated request details are locked. Create a new request for changes.')
        if target in {'To Receive', 'Received', 'Submitted'} and not doc.get(EVIDENCE[1]):
            frappe.throw('Evaluation approval is required before purchasing can proceed.')
