import frappe
from frappe.utils import cstr


def set_unique_job_opening_route(doc, method=None):
    if not doc.name:
        return

    company = cstr(doc.company).strip().lower()
    job_title = cstr(doc.job_title).strip().lower()

    company_slug = frappe.scrub(company).replace("_", "-")
    job_slug = frappe.scrub(job_title).replace("_", "-")
    name_slug = frappe.scrub(doc.name).replace("_", "-")

    doc.route = f"jobs/{company_slug}/{job_slug}/{name_slug}"
