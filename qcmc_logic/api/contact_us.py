import frappe
from frappe.utils import now_datetime

@frappe.whitelist(allow_guest=True)
def send_contact_inquiry():
    """Handle 'Contact Us' form submission, send email to sales, auto-reply to sender, and log communication."""
    data = frappe.form_dict

    # --- Fields ---
    name = data.get("name") or "No Name"
    company = data.get("company") or "N/A"
    contact_no = data.get("contact_no") or "N/A"
    email = data.get("email") or ""
    topic = data.get("topic") or "General Inquiry"
    inquiry = data.get("inquiry") or ""
    hp = data.get("hp")  # honeypot

    # --- Honeypot (silent spam discard)
    if hp:
        return {"message": "OK"}

    # --- Log missing fields (non-blocking)
    missing_fields = []
    if not email:
        missing_fields.append("email")
    if not inquiry:
        missing_fields.append("inquiry")

    if missing_fields:
        frappe.log_error(
            f"Missing fields in contact inquiry: {missing_fields}\nPayload: {data}",
            "Contact Inquiry Missing Fields"
        )

    # --- Timestamp
    time = now_datetime().strftime("%Y-%m-%d %H:%M:%S")

    # --- Email HTML content
    content = f"""
    <div style="font-family: system-ui, sans-serif, Arial; font-size: 12px">
      <div>
        A new <strong>Contact Us</strong> inquiry has been received from <strong>{name}</strong>.
      </div>

      <div
        style="
          margin-top: 20px;
          padding: 15px 0;
          border-width: 1px 0;
          border-style: dashed;
          border-color: lightgrey;
        "
      >
        <table role="presentation">
          <tr>
            <td style="vertical-align: top">
              <div
                style="
                  padding: 6px 10px;
                  margin: 0 10px;
                  background-color: aliceblue;
                  border-radius: 5px;
                  font-size: 26px;
                "
                role="img"
              >
                📩
              </div>
            </td>

            <td style="vertical-align: top">
              <div style="color: #2c3e50; font-size: 16px">
                <strong>Name:</strong> {name}
              </div>
              <div style="color: #2c3e50; font-size: 14px; margin-top: 5px">
                <strong>Company:</strong> {company}
              </div>
              <div style="color: #2c3e50; font-size: 14px; margin-top: 5px">
                <strong>Contact No:</strong> {contact_no}
              </div>
              <div style="color: #2c3e50; font-size: 14px; margin-top: 5px">
                <strong>Email:</strong> {email}
              </div>
              <div style="color: #2c3e50; font-size: 14px; margin-top: 5px">
                <strong>Topic:</strong> {topic}
              </div>
              <div style="color: #cccccc; font-size: 13px; margin-top: 5px">
                {time}
              </div>

              <p style="font-size: 15px; margin-top: 10px">
                <strong>Your Inquiry:</strong><br />
                {inquiry}
              </p>
            </td>
          </tr>
        </table>
      </div>
    </div>
    """

    subject = f"Contact Us Inquiry: {topic}"

     # --- Get Sales email from Email Account Doctype
    sales_email = frappe.db.get_value("Email Account", "Sales QC", "email_id")
    if not sales_email:
        frappe.throw("Sales email account not found.")

    # --- Send email to Sales
    frappe.sendmail(
        recipients=sales_email,
        sender=email if email else "noreply@qcstyro.com",
        subject=subject,
        message=content
    )

    # --- Auto-reply to sender
    if email:
        frappe.sendmail(
            recipients=email,
            subject="We received your inquiry",
            message=f"""
                <p>Hi {name},</p>
                <p>Thank you for contacting <strong>QC StyroPackaging Corporation and MultiPlast Corporation</strong>.</p>
                <p>We have received your inquiry regarding <strong>{topic}</strong> and will get back to you shortly.</p>
                <p>— QC Styro Sales Team</p>
            """
        )

    # --- Log Communication
    frappe.get_doc({
        "doctype": "Communication",
        "communication_type": "Communication",
        "subject": subject,
        "content": content,
        "sent_or_received": "Sent",
        "communication_medium": "Email",
        "sender": email if email else "noreply@qcstyro.com"
    }).insert(ignore_permissions=True)

    return {"message": "Thank you for contacting us. Your inquiry has been sent successfully!"}
