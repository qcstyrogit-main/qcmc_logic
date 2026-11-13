"""Creator-based provincial PR routing; existing documents are grandfathered."""
import frappe
from frappe.utils import cint

ROLE = 'Provincial Stock User'
CREATOR = 'custom_pr_original_creator'
PROVINCIAL = 'custom_pr_provincial_creator'
LOGISTICS = 'Pending Logistics Manager Approval'


def provincial_destination(doc):
    if doc.get('material_request_type') != 'Purchase' or not cint(doc.get(PROVINCIAL)):
        return None
    from qcmc_logic.customs.purchase_request_evaluation import NETWORK, ASSET

    return {'MIS': NETWORK, 'Office Supplies & Equipment': ASSET, 'Motorpool': LOGISTICS}.get(
        doc.get('custom_request_type')
    )


def validate_provincial_origin(doc):
    old = doc.get_doc_before_save()
    if not old:
        # Always derive provenance from the authenticated creator, never client input.
        # Capture on every new Material Request so changing its type later
        # cannot erase who created it. Routing still applies only to Purchase.
        doc.set(CREATOR, frappe.session.user)
        doc.set(PROVINCIAL, int(ROLE in frappe.get_roles()))
        return
    if doc.get(CREATOR) != old.get(CREATOR) or cint(doc.get(PROVINCIAL)) != cint(old.get(PROVINCIAL)):
        frappe.throw('Purchase request creator classification is maintained by the server.')
    purchase = 'Purchase' in (old.get('material_request_type'), doc.get('material_request_type'))
    if purchase and old.get(CREATOR) and doc.get('owner') != old.get('owner'):
        frappe.throw('The original Purchase request owner cannot be changed.')


def validate_provincial_route(doc):
    old = doc.get_doc_before_save()
    if not old:
        if provincial_destination(doc) and (doc.get('workflow_state') not in (None, '', 'Draft') or doc.get('docstatus', 0) != 0):
            frappe.throw('New provincial Purchase requests must start in Draft.')
        return
    required = provincial_destination(old)
    current, target = old.get('workflow_state'), doc.get('workflow_state')
    if current == 'Draft':
        if required and doc.get('docstatus', 0) != 0:
            frappe.throw('Submit this provincial request for approval before purchasing can proceed.')
        if target != current and (required or provincial_destination(doc)):
            if doc.get('custom_request_type') != old.get('custom_request_type') or doc.get('material_request_type') != old.get('material_request_type'):
                frappe.throw('Save request type changes before submitting for approval.')
            if target != required:
                frappe.throw('This provincial request must follow its designated approval route.')
            if old.get(CREATOR) != frappe.session.user or ROLE not in frappe.get_roles():
                frappe.throw('Only the provincial creator can submit this request for approval.')
    elif required:
        # Keep the chosen route stable throughout Logistics/evaluation/purchasing.
        for key in ('material_request_type', 'custom_request_type'):
            if doc.get(key) != old.get(key):
                frappe.throw('The request type cannot change after provincial approval routing begins.')
        if required == LOGISTICS and current == LOGISTICS:
            if doc.get('docstatus', 0) != 0:
                frappe.throw('Logistics approval is required before submitting this request.')
            if target != current and target not in {'To Receive', 'Cancelled Before Submission'}:
                frappe.throw('Provincial Motorpool requests require Logistics approval.')
            if target == 'To Receive' and 'Logistics Manager' not in frappe.get_roles():
                frappe.throw('Only a Logistics Manager can approve this request.')


def has_other_permission(doc, ptype, user):
    """Whether a pre-existing role grants access independently of the new role."""
    roles = set(frappe.get_roles(user)) - {ROLE}
    permission = ptype or 'read'
    return any(row.role in roles and row.get(permission)
               and (not row.get('if_owner') or not doc or doc.get('owner') == user)
               for row in frappe.get_meta('Material Request').permissions)


def restrict_provincial_permission(doc, ptype, user):
    if ROLE not in frappe.get_roles(user) or has_other_permission(doc, ptype, user):
        return None
    # The new grant is only for the creator's Purchase requests, never other MR types.
    if doc.get('material_request_type') != 'Purchase':
        return False
    if ptype == 'write' and doc.get('name'):
        state = frappe.db.get_value('Material Request', doc.name, 'workflow_state')
        if state and state != 'Draft':
            return False
    return None
