import frappe
from frappe.utils import get_fullname, now_datetime

def mrf_approver_before_save(doc, method):
    user_roles = [r.role for r in frappe.get_all("Has Role", filters={"parent": frappe.session.user}, fields=["role"])]
    bcclt_roles = ['Comptroller', 'VP Sales', 'VP Purchasing']
    has_bcclt_role = any(role in bcclt_roles for role in user_roles)
    has_corp_ie_role = 'Corporate IE Head' in user_roles

    if doc.workflow_state == "Approved":
        if has_corp_ie_role:
            doc.custom_approved_by_corp_ie = get_fullname(frappe.session.user)
            doc.custom_corp_ie_approve_date = now_datetime()
        elif has_bcclt_role:
            doc.custom_approved_by_bcclt = get_fullname(frappe.session.user)
            doc.custom_bcclt_approve_date = now_datetime()
        else:
            doc.custom_approved_by_manager = get_fullname(frappe.session.user)
            doc.custom_manager_approve_date = now_datetime()
    elif doc.workflow_state in ["For BCC Approval","For VP Procurement","For VP Sales Approval"]:
        doc.custom_approved_by_manager = get_fullname(frappe.session.user)
        doc.custom_manager_approve_date = now_datetime()
    elif doc.workflow_state == "Acknowledged":
        doc.custom_acknowledged_by = get_fullname(frappe.session.user)
        doc.custom_hr_acknowledged_date = now_datetime()
