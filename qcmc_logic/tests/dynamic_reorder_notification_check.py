"""Local-only native notification insert, deduplication and rollback."""
from unittest.mock import patch
from datetime import date
import frappe
from qcmc_logic import dynamic_reorder_notifications as n

def run():
    assert frappe.local.site=="erp.qcstyro.local" and frappe.session.user=="Administrator"
    settings=frappe.get_single("Reorder Settings")
    assert settings.preview_only and not settings.automatic_update_enabled
    assert not settings.get("email_execution_alerts"),"Disable email execution alerts before testing"
    day=date(2099,1,1)
    assert not frappe.db.exists(n.EXECUTION,{"scheduled_date":day})
    name=None
    output=[]
    try:
        with patch.object(frappe,"publish_realtime"),patch.object(frappe,"sendmail") as mail,patch.object(frappe.db,"commit",side_effect=RuntimeError("Commit forbidden")),patch("frappe.desk.doctype.notification_settings.notification_settings.is_notifications_enabled",return_value=True):
            run=frappe.get_doc(dict(doctype=n.EXECUTION,scheduled_date=day,status="Completed",attempts=1,catch_up=1)).insert(ignore_permissions=True)
            name=run.name
            result=dict(recorded=4,review=2,failed=0)
            assert n.notify_execution(name,"catch_up",result)
            assert not n.notify_execution(name,"catch_up",result)
            assert n.notify_execution(name,"approval",result)
            logs=frappe.get_all("Notification Log",filters={"document_type":n.EXECUTION,"document_name":name},fields=["for_user","type","subject","email_content"])
            assert len(logs)==2 and all(x.for_user=="Administrator" and x.type=="Alert" for x in logs),logs
            assert all("Review: 2" in x.email_content for x in logs)
            mail.assert_not_called()
            output.append("PASS: native Administrator alerts link to execution, contain counts and deduplicate")
            output.append("PASS: email disabled by default")
            frappe.db.set_value(n.EXECUTION,name,{"attempts":2,"status":"Retry Pending"})
            assert n.notify_execution(name,"retry",{"failed":1})
            assert not n.notify_execution(name,"retry",{"failed":1})
            output.append("PASS: retries have separate deduplicated alerts")
    finally:
        frappe.db.rollback()
    assert not frappe.db.exists(n.EXECUTION,{"scheduled_date":day})
    assert not name or not frappe.db.exists("Notification Log",{"document_type":n.EXECUTION,"document_name":name})
    output.append("PASS: temporary execution and notification records rolled back")
    return output
