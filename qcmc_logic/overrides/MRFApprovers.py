import frappe
from hrms.hr.doctype.job_requisition.job_requisition import JobRequisition as OriginalJobRequisition

class MRFApproverSetCustomFields(OriginalJobRequisition):
    def before_save(self):
        """Auto-fill approval fields based on workflow state and user roles."""
        user_roles = [r.role for r in frappe.db.get_all("Has Role", filters={"parent": frappe.session.user}, fields=["role"])]
        print("User Roles:", user_roles)  # DEBUG: list of roles

        bcclt_roles = ['Comptroller', 'VP Sales', 'VP Purchasing']
        has_bcclt_role = any(role in bcclt_roles for role in user_roles)
        has_corp_ie_role = 'Corporate IE Head' in user_roles

        print("Has BCCLT Role?", has_bcclt_role)  # DEBUG: check if user is in BCCLT
        print("Has Corporate IE Role?", has_corp_ie_role)  # DEBUG

        # Main logic
        if self.workflow_state == "Approved":
            if has_corp_ie_role:
                self.custom_approved_by_corp_ie = frappe.utils.get_fullname(frappe.session.user)
                self.custom_corp_ie_approve_date = frappe.utils.now_datetime()

            elif has_bcclt_role:
                self.custom_approved_by_bcclt = frappe.utils.get_fullname(frappe.session.user)
                self.custom_bcclt_approve_date = frappe.utils.now_datetime()

            else:
                self.custom_approved_by_manager = frappe.utils.get_fullname(frappe.session.user)
                self.custom_manager_approve_date = frappe.utils.now_datetime()

        elif self.workflow_state in ["For BCC Approval","For VP Procurement","For VP Sales Approval"]:
            self.custom_approved_by_manager = frappe.utils.get_fullname(frappe.session.user)
            self.custom_manager_approve_date = frappe.utils.now_datetime()

        elif self.workflow_state == "Acknowledged":
            # HR acknowledgement
            self.custom_acknowledged_by = frappe.utils.get_fullname(frappe.session.user)
            self.custom_hr_acknowledged_date = frappe.utils.now_datetime()





