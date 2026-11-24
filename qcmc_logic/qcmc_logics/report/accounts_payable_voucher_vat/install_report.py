"""Register this standard report on local development site without running unrelated patches."""
import frappe

def execute():
    report_name = "Accounts Payable Voucher VAT"
    if frappe.db.exists("Report", report_name):
        report = frappe.get_doc("Report", report_name)
        if report.report_type != "Script Report" or report.ref_doctype != "Purchase Invoice":
            frappe.throw("Existing report name conflicts with the intended report")
        return "already registered"
    doc = frappe.get_doc({
        "doctype": "Report",
        "report_name": report_name,
        "ref_doctype": "Purchase Invoice",
        "module": "QCMC Logics",
        "report_type": "Script Report",
        "is_standard": "Yes",
        "roles": [{"role": role} for role in ("Accounts User","Accounts Manager","System Manager")],
    })
    doc.insert(ignore_permissions=True)
    frappe.db.commit()
    return "registered"
