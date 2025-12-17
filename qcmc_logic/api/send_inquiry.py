import frappe

@frappe.whitelist(allow_guest=True)
def send_inquiry():
    """
    Guest-safe inquiry submission.
    CSRF check is disabled for this method.
    """
    # Ignore CSRF before doing anything else
    frappe.local.flags.ignore_csrf = True

    # Get request payload
    data = frappe.request.get_json(silent=True) or frappe.form_dict

    name = data.get("name") or "No Name"
    email = data.get("email") or ""
    contact = data.get("contact") or "N/A"
    product = data.get("product") or "N/A"
    message = data.get("message") or ""
    hp = data.get("hp")

    # Honeypot
    if hp:
        return {"message": "OK"}

    # Log missing fields
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

    subject = f"Product Inquiry: {product}"
    content = f"""
    <p><strong>Product:</strong> {product}</p>
    <p><strong>Name:</strong> {name}</p>
    <p><strong>Email:</strong> {email or '(No email provided)'}</p>
    <p><strong>Contact:</strong> {contact}</p>
    <p><strong>Message:</strong><br>{message or '(No message provided)'}</p>
    """

    # Send email via default outgoing account
    frappe.sendmail(
        recipients="mmagbojos@qcstyro.com",
        sender=email if email else "noreply@qcstyro.com",
        subject=subject,
        message=content
    )

    # Log Communication
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
