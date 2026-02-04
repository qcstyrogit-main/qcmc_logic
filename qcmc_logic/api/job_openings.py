import frappe
from frappe.utils import now_datetime

@frappe.whitelist(allow_guest=True)
def get_job_openings():
    jobs = frappe.get_all(
        "Job Opening",
        fields=[
            "name",
            "job_title",
            "company",
            "department",
            "creation",
            "location",
            "salary_per",
            "lower_range",
            "upper_range",
            "publish_salary_range",
            "employment_type",
            "description"
        ],
        filters={"status": "Open"},
        order_by="creation desc",
        limit_page_length=0
    )

    today = now_datetime().date()
    job_list = []

    for j in jobs:
        posted_days = (today - j.creation.date()).days if j.creation else 0

        # Salary
        if j.publish_salary_range:
            lower = f"₱ {j.lower_range:,.0f}" if j.lower_range else "N/A"
            upper = f"₱ {j.upper_range:,.0f}" if j.upper_range else "N/A"
            salary = f"{lower} - {upper} / {j.salary_per}" if j.lower_range and j.upper_range else "N/A"
        else:
            salary = "N/A"

        # Count applicants using the job title string
        applicants_count = frappe.db.count(
            "Job Applicant",
            filters={
                "job_title": j.job_title,  # <-- this is the fix
                "status": "Applied"
            }
        )

        job_list.append({
            "name": j.name,
            "title": j.job_title,
            "company": j.company,
            "department": j.department,
            "location": j.location or "N/A",
            "salary": salary,
            "postedDays": posted_days,
            "applicants": applicants_count or 0,
            "employment_type": j.employment_type or "N/A",
            "description": j.description or ""
        })

    return job_list

@frappe.whitelist(allow_guest=True)
def get_job_applicant_counts():
    # This groups applicants by the 'job_title' field (which links to the Job Opening ID)
    counts = frappe.db.sql("""
        SELECT job_title, COUNT(*) as count 
        FROM `tabJob Applicant` 
        GROUP BY job_title
    """, as_dict=True)
    
    # Convert list of dicts to a single dictionary: {"HR-OPN-0001": 5, ...}
    return {d.job_title: d.count for d in counts}



@frappe.whitelist(allow_guest=True)
def submit_job_applicant_custom(
    job_title, applicant_name, address, email_id, phone_number,
    custom_referrer=None, cover_letter=None, resume_link=None,
    currency=None, lower_range=None, upper_range=None,
    custom_i_agree_to_the_data_privacy_statement=1, custom_current_job_position=None
):
    doc = frappe.get_doc({
        "doctype": "Job Applicant",
        "web_form_name": "job-application-form",
        "job_title": job_title,
        "applicant_name": applicant_name,
        "address": address,
        "email_id": email_id,
        "phone_number": phone_number,

        # 🔴 THIS IS THE MISSING PIECE
        "status": "Open",

        "custom_referrer": custom_referrer,
        "cover_letter": cover_letter,
        "resume_link": resume_link,
        "currency": currency,
        "lower_range": lower_range,
        "upper_range": upper_range,
        "custom_i_agree_to_the_data_privacy_statement": int(custom_i_agree_to_the_data_privacy_statement),
        "custom_current_job_position": custom_current_job_position
    })

    doc.flags.ignore_permissions = True
    doc.insert()          # triggers Notification (after_insert)
    doc.notify_update()
    frappe.db.commit()
    

    return {
        "message": "Saved",
        "docname": doc.name
    }




