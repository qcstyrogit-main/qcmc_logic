"""Native administrator alerts for monthly reorder execution."""
import frappe
from frappe.utils import escape_html

EXECUTION = "Reorder Execution History"

def notify_execution(name, event, result=None, superseded=0):
    """Called under scheduler lock. Only Administrator can open execution history."""
    from frappe.desk.doctype.notification_settings.notification_settings import is_notifications_enabled
    run=frappe.get_doc(EXECUTION,name)
    if not frappe.db.get_value("User","Administrator","enabled") or not is_notifications_enabled("Administrator"):
        return False
    result=result or {}
    labels={
        "completed":"Scheduled calculation completed",
        "catch_up":"Missed schedule recovered (preview only)",
        "superseded":"Older schedules superseded",
        "approval":"Calculations require approval",
        "retry":"Calculation retry pending",
        "failed":"Critical: retry limit exhausted",
        "unexpected":"Critical: unexpected scheduler failure",
    }
    subject=f"Reorder: {labels[event]} | {run.scheduled_date} | attempt {run.attempts}"
    filters=dict(for_user="Administrator",document_type=EXECUTION,document_name=name,subject=subject)
    if frappe.db.exists("Notification Log",filters):
        return False
    summary=f"Scheduled date: {run.scheduled_date}; status: {run.status}; attempt: {run.attempts}."
    for k in ("recorded","duplicates","applied","review","failed","item_failed"):
        if k in result:
            summary+=f" {k.title()}: {int(result[k] or 0)}."
    if superseded:
        summary+=f" Superseded schedules: {int(superseded)}."
    if event in ("retry","failed","unexpected"):
        summary+=" Review execution history and Error Log."
    frappe.get_doc(dict(doctype="Notification Log",**filters,from_user="Administrator",type="Alert",email_content=escape_html(summary))).insert(ignore_permissions=True)
    # Native Alert does not send email; opt-in uses the standard outgoing queue.
    settings=frappe.get_single("Reorder Settings")
    if settings.get("email_execution_alerts"):
        email=frappe.db.get_value("User","Administrator","email")
        if email and "@" in email and frappe.db.exists("Email Account",{"enable_outgoing":1,"default_outgoing":1}):
            from frappe.utils import get_url_to_form
            frappe.sendmail(recipients=[email],subject=subject,message=escape_html(summary)+"<p><a href='"+escape_html(get_url_to_form(EXECUTION,name))+"'>Open execution history</a></p>",now=False)
    return True

def safe_notify(name,event,result=None,superseded=0):
    """Notification failure must not undo a calculation or trigger another application."""
    frappe.db.savepoint("reorder_notification")
    try:
        return notify_execution(name,event,result,superseded)
    except Exception:
        frappe.db.rollback(save_point="reorder_notification")
        frappe.log_error(title="Reorder notification delivery failed")
        return False
