import frappe
from frappe.utils import now_datetime
from frappe.utils.file_manager import save_file

@frappe.whitelist(allow_guest=True)
def get_job_openings():
    """Fetch open job listings with details and applicant counts."""
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
    """Fetch counts of applicants grouped by job title."""
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

    # --- Handle File Attachment (Resume)
    resume_attachment = None
    if frappe.request.files:
        for file_key in frappe.request.files:
            if file_key == "resume_file":
                file_content = frappe.request.files[file_key]
                file_doc = save_file(
                    file_content.filename,
                    file_content.read(),
                    doc.doctype,
                    doc.name,
                    is_private=1
                )
                resume_attachment = file_doc.file_url

    # --- Email Logic
    subject = f"New Job Application: {job_title} - {applicant_name}"
    time = now_datetime().strftime("%Y-%m-%d %H:%M:%S")

    # Construct Admin Email Content
    admin_content = f"""
    <div style="font-family: system-ui, sans-serif, Arial; font-size: 14px; line-height: 1.6; color: #333;">
      <h2 style="color: #133880; border-bottom: 2px solid #ed1d26; padding-bottom: 8px;">New Job Application</h2>
      <p>A new application has been received for the position of <strong>{job_title}</strong>.</p>
      
      <table role="presentation" style="width: 100%; margin-top: 20px; border-collapse: collapse;">
        <tr><td style="padding: 8px; border-bottom: 1px solid #eee;"><strong>Applicant Name:</strong></td><td style="padding: 8px; border-bottom: 1px solid #eee;">{applicant_name}</td></tr>
        <tr><td style="padding: 8px; border-bottom: 1px solid #eee;"><strong>Email:</strong></td><td style="padding: 8px; border-bottom: 1px solid #eee;">{email_id}</td></tr>
        <tr><td style="padding: 8px; border-bottom: 1px solid #eee;"><strong>Phone:</strong></td><td style="padding: 8px; border-bottom: 1px solid #eee;">{phone_number}</td></tr>
        <tr><td style="padding: 8px; border-bottom: 1px solid #eee;"><strong>Position:</strong></td><td style="padding: 8px; border-bottom: 1px solid #eee;">{custom_current_job_position or 'N/A'}</td></tr>
        <tr><td style="padding: 8px; border-bottom: 1px solid #eee;"><strong>Resume Link:</strong></td><td style="padding: 8px; border-bottom: 1px solid #eee;">{resume_link or 'See Attachment'}</td></tr>
        <tr><td style="padding: 8px; border-bottom: 1px solid #eee;"><strong>Expected Salary:</strong></td><td style="padding: 8px; border-bottom: 1px solid #eee;">{currency or 'PHP'} {lower_range or 0:,.0f} - {upper_range or 0:,.0f}</td></tr>
      </table>

      <div style="margin-top: 25px; padding: 15px; background-color: #f9fafb; border-radius: 8px;">
        <strong>Cover Letter:</strong><br/>
        <p style="white-space: pre-wrap;">{cover_letter or 'No cover letter provided.'}</p>
      </div>
      
      <p style="color: #999; font-size: 12px; margin-top: 30px;">Submitted on: {time}</p>
    </div>
    """

    # Get Career Emails
    career1 = frappe.db.get_value("Email Account", "Career 1", "email_id")
    career2 = frappe.db.get_value("Email Account", "Career 2", "email_id")
    
    recipients = []
    if career1: recipients.append(career1)
    if career2: recipients.append(career2)

    # Attachments list for frappe.sendmail
    mail_attachments = []
    if resume_attachment:
        # Get absolute path for file if internal
        if resume_attachment.startswith("/private/files/"):
            mail_attachments.append({
                "fname": file_doc.file_name,
                "fcontent": frappe.get_doc("File", file_doc.name).get_content()
            })

    # 1. Send to Career Team
    if recipients:
        frappe.sendmail(
            recipients=recipients,
            subject=subject,
            message=admin_content,
            attachments=mail_attachments
        )

    # 2. Send Auto-reply to Applicant
    if email_id:
        frappe.sendmail(
            recipients=email_id,
            subject=f"Application Received: {job_title}",
            message=f"""
                <p>Dear {applicant_name},</p>
                <p>Thank you for applying for the <strong>{job_title}</strong> position at QC StyroPackaging / MultiPlast Corporation.</p>
                <p>We have received your application and resume. Our recruitment team will review your qualifications and contact you if your profile matches our requirements.</p>
                <p>Best regards,<hr/><strong>HR Recruitment Team</strong></p>
            """
        )

    # 3. Log Communication
    frappe.get_doc({
        "doctype": "Communication",
        "communication_type": "Communication",
        "subject": subject,
        "content": admin_content,
        "sent_or_received": "Received",
        "communication_medium": "Email",
        "sender": email_id
    }).insert(ignore_permissions=True)

    frappe.db.commit()
    

    return {
        "message": "Saved",
        "docname": doc.name
    }




