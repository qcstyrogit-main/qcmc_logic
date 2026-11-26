"""The Stockroom MC route requires Maintenance Head before MC Plant Manager."""
import frappe
from frappe.utils import cint, now_datetime
from qcmc_logic.customs.mc_purchase_request import (
    MAINTENANCE_ROLE as ROLE, MAINTENANCE_STATE as STATE, MANAGER, QC_COMPANY, requires_mc_ppic,
)

REQUESTER = 'Stockroom_PR_MC_lv1'
REQUIRED = 'custom_pr_mc_maintenance_required'
APPROVED_BY = 'custom_pr_mc_maintenance_approved_by'
APPROVED_ON = 'custom_pr_mc_maintenance_approved_on'
FIELDS = (REQUIRED, APPROVED_BY, APPROVED_ON)


def eligible(doc):
    from qcmc_logic.customs.provincial_purchase_request import provincial_destination

    return (doc.get('material_request_type') == 'Purchase' and bool(doc.get('company'))
            and doc.get('company') != QC_COMPANY and not provincial_destination(doc)
            and not requires_mc_ppic(doc))


def validate_maintenance(doc):
    old = doc.get_doc_before_save()
    if not old:
        if cint(doc.get(REQUIRED)) or doc.get(APPROVED_BY) or doc.get(APPROVED_ON):
            frappe.throw('MC Maintenance Head approval history is maintained by the server.')
        return
    if cint(doc.get(REQUIRED)) != cint(old.get(REQUIRED)) or any(
        str(doc.get(field) or '') != str(old.get(field) or '') for field in (APPROVED_BY, APPROVED_ON)
    ):
        frappe.throw('MC Maintenance Head approval history is maintained by the server.')
    source, target = old.get('workflow_state'), doc.get('workflow_state')
    if source == 'Draft' and eligible(old) and REQUESTER in frappe.get_roles() and doc.get('docstatus', 0) != 0:
        frappe.throw('Send this Stockroom MC request for approval before submitting it.')
    if target == STATE and source != STATE:
        if source != 'Draft' or not eligible(old) or REQUESTER not in frappe.get_roles() or old.get('owner') != frappe.session.user:
            frappe.throw('MC Maintenance Head approval must follow the Stockroom MC Draft route.')
        if any(doc.get(field) != old.get(field) for field in ('company', 'material_request_type', 'custom_request_type')):
            frappe.throw('Save request type and company changes before requesting approval.')
        if doc.get('docstatus', 0) != 0:
            frappe.throw('Maintenance approval requests must remain draft internally.')
        doc.set(REQUIRED, 1)
    if source == STATE:
        if not cint(old.get(REQUIRED)):
            frappe.throw('This request has invalid MC Maintenance Head approval history.')
        if doc.get('docstatus', 0) != 0:
            frappe.throw('MC Maintenance Head approval is required before submission.')
        if target == MANAGER:
            if ROLE not in frappe.get_roles():
                frappe.throw('Only an MC Maintenance Head can approve this request.')
            doc.set(APPROVED_BY, frappe.session.user)
            doc.set(APPROVED_ON, now_datetime())
        elif target != source and target != 'Cancelled Before Submission':
            frappe.throw('MC Maintenance Head approval must proceed to Plant Manager MC.')
    if cint(old.get(REQUIRED)):
        if any(doc.get(field) != old.get(field) for field in ('company', 'material_request_type', 'custom_request_type')):
            frappe.throw('Request type and company cannot change after maintenance routing begins.')
        if source != STATE and not old.get(APPROVED_BY):
            frappe.throw('MC Maintenance Head approval must be completed before this request can proceed.')
