"""MC RMFS creator routing with the established provincial exceptions."""
import frappe
from frappe.utils import cint, now_datetime

REQUESTER = 'RMFS_PR_MC'
SUPERVISOR = 'MC PPIC Supervisor'
STATE = 'Pending MC PPIC Supervisor'
MANAGER = 'Pending MC PM Approval'
CREATOR_FLAG = 'custom_pr_mc_rmfs_creator'
APPROVED_BY = 'custom_pr_mc_ppic_approved_by'
APPROVED_ON = 'custom_pr_mc_ppic_approved_on'
QC_COMPANY = 'QC Styropackaging Corporation'
MAINTENANCE_ROLE = 'MC Maintenance Head'
MAINTENANCE_STATE = 'Pending MC Maintenance Head Approval'


def requires_mc_ppic(doc):
    from qcmc_logic.customs.provincial_purchase_request import provincial_destination

    return (doc.get('material_request_type') == 'Purchase' and cint(doc.get(CREATOR_FLAG))
            and bool(doc.get('company')) and doc.get('company') != QC_COMPANY
            and not provincial_destination(doc))


def validate_mc_origin(doc):
    old = doc.get_doc_before_save()
    if not old:
        doc.set(CREATOR_FLAG, int(REQUESTER in frappe.get_roles()))
        if doc.get(APPROVED_BY) or doc.get(APPROVED_ON):
            frappe.throw('MC PPIC approval history cannot be supplied on a new request.')
        return
    if cint(doc.get(CREATOR_FLAG)) != cint(old.get(CREATOR_FLAG)):
        frappe.throw('MC RMFS creator classification is maintained by the server.')
    for field in (APPROVED_BY, APPROVED_ON):
        if str(doc.get(field) or '') != str(old.get(field) or ''):
            frappe.throw('MC PPIC approval history is maintained by the server.')


def validate_mc_route(doc):
    old = doc.get_doc_before_save()
    if not old:
        if requires_mc_ppic(doc) and (doc.get('workflow_state') not in (None, '', 'Draft') or doc.get('docstatus', 0) != 0):
            frappe.throw('MC RMFS Purchase requests must start in Draft.')
        return
    source, target = old.get('workflow_state'), doc.get('workflow_state')
    required = requires_mc_ppic(old)
    if target == STATE and not required:
        frappe.throw('MC PPIC routing is available only for an eligible MC RMFS request.')
    if source == 'Draft':
        if required and doc.get('docstatus', 0) != 0:
            frappe.throw('MC PPIC approval is required before submission.')
        if target != source and (required or requires_mc_ppic(doc)):
            for field in ('material_request_type', 'custom_request_type', 'company'):
                if doc.get(field) != old.get(field):
                    frappe.throw('Save request type and company changes before submitting for MC PPIC approval.')
            if target != STATE:
                frappe.throw('This request must first pass through MC PPIC Supervisor approval.')
            if old.get('owner') != frappe.session.user or REQUESTER not in frappe.get_roles():
                frappe.throw('Only the MC RMFS creator can submit this request for approval.')
    elif required:
        for field in ('material_request_type', 'custom_request_type', 'company'):
            if doc.get(field) != old.get(field):
                frappe.throw('Request type and company cannot change after MC approval routing begins.')
        if source == STATE:
            if doc.get('docstatus', 0) != 0:
                frappe.throw('MC PPIC approval is required before submission.')
            if target == MANAGER:
                if SUPERVISOR not in frappe.get_roles():
                    frappe.throw('Only an MC PPIC Supervisor can approve this request.')
                doc.set(APPROVED_BY, frappe.session.user)
                doc.set(APPROVED_ON, now_datetime())
            elif target != source and target != 'Cancelled Before Submission':
                frappe.throw('MC PPIC approval must proceed to Plant Manager MC.')
        elif not old.get(APPROVED_BY):
            frappe.throw('MC PPIC approval must be completed before this request can proceed.')
    elif target == STATE and target != source:
        frappe.throw('MC PPIC routing is available only for an eligible MC RMFS request.')


def has_independent_permission(doc, ptype, user):
    roles = set(frappe.get_roles(user))
    if not roles.intersection({REQUESTER, SUPERVISOR, MAINTENANCE_ROLE}):
        return True
    roles -= {REQUESTER, SUPERVISOR, MAINTENANCE_ROLE, 'Provincial Stock User'}
    return any(row.role in roles and row.get(ptype or 'read')
               and (not row.get('if_owner') or not doc or doc.get('owner') == user)
               for row in frappe.get_meta('Material Request').permissions)


def restrict_mc_permission(doc, ptype, user):
    if has_independent_permission(doc, ptype, user):
        return None
    if doc.get('material_request_type') != 'Purchase':
        return False
    if ptype == 'write':
        state = frappe.db.get_value('Material Request', doc.name, 'workflow_state') if doc.get('name') else None
        roles = frappe.get_roles(user)
        if state == STATE and SUPERVISOR in roles:
            return None
        if state == MAINTENANCE_STATE and MAINTENANCE_ROLE in roles:
            return None
        if state in (None, 'Draft') and doc.get('owner') == user and REQUESTER in roles:
            return None
        return False
    return None
