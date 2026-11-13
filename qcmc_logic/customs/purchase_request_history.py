"""Server-maintained approval membership and a personal list-view preference."""
import json

import frappe
import frappe.defaults
from frappe.utils import cint

FIELD = 'custom_pr_previous_approvers'
PREFERENCE = 'qcmc_include_previously_approved_prs'


def approved_users(value):
    if not value:
        return []
    try:
        users = json.loads(value) if isinstance(value, str) else value
    except (TypeError, ValueError):
        return []
    return users if isinstance(users, list) and all(isinstance(user, str) for user in users) else []


def is_approval(source, target):
    from qcmc_logic.customs.purchase_request_workflow import APPROVAL_STATES, TERMINAL_STATES

    return source in APPROVAL_STATES and target and target != source and target not in TERMINAL_STATES


def validate_history(doc):
    old = doc.get_doc_before_save()
    if not old:
        if approved_users(doc.get(FIELD)):
            frappe.throw('Previous approvers are recorded by the server.')
        doc.set(FIELD, None)
        return
    if doc.get(FIELD) != old.get(FIELD):
        frappe.throw('Previous approvers are recorded by the server.')
    if old.get('material_request_type') == doc.get('material_request_type') == 'Purchase' and is_approval(
        old.get('workflow_state'), doc.get('workflow_state')
    ):
        users = approved_users(old.get(FIELD))
        if frappe.session.user not in users:
            doc.set(FIELD, json.dumps(users + [frappe.session.user]))


def previously_approved(doc, user):
    return user in approved_users(doc.get(FIELD))


def include_previous_approvals(user):
    return bool(cint(frappe.defaults.get_user_default(PREFERENCE, user=user)))


def history_condition(user):
    return (
        "JSON_CONTAINS(COALESCE(NULLIF(`tabMaterial Request`.custom_pr_previous_approvers, ''), '[]'), "
        f"JSON_QUOTE({frappe.db.escape(user)}))"
    )


@frappe.whitelist()
def get_history_preference():
    return int(include_previous_approvals(frappe.session.user))


@frappe.whitelist()
def get_previous_approval_count():
    # Use normal document and warehouse permissions, including the saved list
    # preference. This is feedback, never an alternate way to grant access.
    rows = frappe.get_list('Material Request',
                           filters={'material_request_type': 'Purchase', FIELD: ['is', 'set']},
                           fields=[FIELD], limit_page_length=0)
    return sum(previously_approved(row, frappe.session.user) for row in rows)


@frappe.whitelist()
def set_history_preference(enabled):
    if str(enabled) not in {'0', '1'}:
        frappe.throw('Invalid approval-history preference.')
    frappe.defaults.set_user_default(PREFERENCE, cint(enabled), user=frappe.session.user)
    return cint(enabled)
