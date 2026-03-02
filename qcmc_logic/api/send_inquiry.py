import frappe
from frappe.utils import now_datetime

@frappe.whitelist(allow_guest=True)
def send_inquiry_qc():
    """Handle 'Contact Us' form submission, send email to sales, auto-reply to sender, and log communication."""
    data = frappe.form_dict

    name = data.get("name") or "No Name"
    email = data.get("email") or ""
    contact = data.get("contact") or "N/A"
    product = data.get("product") or "N/A"
    message = data.get("message") or ""
    hp = data.get("hp")

    # --- Honeypot (silent spam discard)
    if hp:
        return {"message": "OK"}

    # --- Log missing fields (non-blocking)
    missing_fields = []
    if not email:
        missing_fields.append("email")
    if not message:
        missing_fields.append("message")

    if missing_fields:
        frappe.log_error(
            f"Missing fields in inquiry: {missing_fields}\nPayload: {data}",
            "Inquiry Missing Fields"
        )

    # --- Timestamp
    time = now_datetime().strftime("%Y-%m-%d %H:%M:%S")

    # --- Email HTML template
    content = f"""
    <div style="font-family: system-ui, sans-serif, Arial; font-size: 12px">
      <div>
        A new product inquiry has been received from <strong>{name}</strong>. Kindly respond at your earliest convenience.
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
                📦
              </div>
            </td>

            <td style="vertical-align: top">
              <div style="color: #2c3e50; font-size: 16px">
                <strong>Name:</strong> {name}
              </div>
              <div style="color: #2c3e50; font-size: 16px; margin-top: 5px">
                <strong>Product:</strong> {product}
              </div>
              <div style="color: #2c3e50; font-size: 14px; margin-top: 5px">
                <strong>Contact Number:</strong> {contact}
              </div>
              <div style="color: #2c3e50; font-size: 14px; margin-top: 5px">
                <strong>Email Address:</strong> {email}
              </div>
              <div style="color: #cccccc; font-size: 13px; margin-top: 5px">
                {time}
              </div>
              <p style="font-size: 15px; margin-top: 10px">
                <strong>Message:</strong><br />
                {message}
              </p>
            </td>
          </tr>
        </table>
      </div>
    </div>
    """

    subject = f"Product Inquiry: {product}"

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

    # --- Auto-reply to guest
    if email:
        frappe.sendmail(
            recipients=email,
            subject="We received your inquiry",
            message=f"""
                <p>Hi {name},</p>
                <p>Thank you for your inquiry about <strong>{product}</strong>.</p>
                <p>Our team has received your message and will contact you shortly.</p>
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

    return {"message": "Inquiry submitted successfully!"}


@frappe.whitelist(allow_guest=True)
def send_inquiry_mc():
    data = frappe.form_dict

    name = data.get("name") or "No Name"
    email = data.get("email") or ""
    contact = data.get("contact") or "N/A"
    product = data.get("product") or "N/A"
    message = data.get("message") or ""
    hp = data.get("hp")

    # --- Honeypot (silent spam discard)
    if hp:
        return {"message": "OK"}

    # --- Log missing fields (non-blocking)
    missing_fields = []
    if not email:
        missing_fields.append("email")
    if not message:
        missing_fields.append("message")

    if missing_fields:
        frappe.log_error(
            f"Missing fields in inquiry: {missing_fields}\nPayload: {data}",
            "Inquiry Missing Fields"
        )

    # --- Timestamp
    time = now_datetime().strftime("%Y-%m-%d %H:%M:%S")

    # --- Email HTML template
    content = f"""
    <div style="font-family: system-ui, sans-serif, Arial; font-size: 12px">
      <div>
        A new product inquiry has been received from <strong>{name}</strong>. Kindly respond at your earliest convenience.
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
                📦
              </div>
            </td>

            <td style="vertical-align: top">
              <div style="color: #2c3e50; font-size: 16px">
                <strong>Name:</strong> {name}
              </div>
              <div style="color: #2c3e50; font-size: 16px; margin-top: 5px">
                <strong>Product:</strong> {product}
              </div>
              <div style="color: #2c3e50; font-size: 14px; margin-top: 5px">
                <strong>Contact Number:</strong> {contact}
              </div>
              <div style="color: #2c3e50; font-size: 14px; margin-top: 5px">
                <strong>Email Address:</strong> {email}
              </div>
              <div style="color: #cccccc; font-size: 13px; margin-top: 5px">
                {time}
              </div>
              <p style="font-size: 15px; margin-top: 10px">
                <strong>Message:</strong><br />
                {message}
              </p>
            </td>
          </tr>
        </table>
      </div>
    </div>
    """

    subject = f"Product Inquiry: {product}"

    # --- Get Sales email from Email Account Doctype
    sales_email = frappe.db.get_value("Email Account", "Sales MC", "email_id")
    if not sales_email:
        frappe.throw("Sales email account not found.")

    # --- Send email to Sales
    frappe.sendmail(
        recipients=sales_email,
        sender=email if email else "noreply@qcstyro.com",
        subject=subject,
        message=content
    )

    # --- Auto-reply to guest
    if email:
        frappe.sendmail(
            recipients=email,
            subject="We received your inquiry",
            message=f"""
                <p>Hi {name},</p>
                <p>Thank you for your inquiry about <strong>{product}</strong>.</p>
                <p>Our team has received your message and will contact you shortly.</p>
                <p>— MC Plast Sales Team</p>
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

    return {"message": "Inquiry submitted successfully!"}
