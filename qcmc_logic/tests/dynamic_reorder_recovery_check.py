"""Local scheduler recovery integration: actual execution records, rolled back."""
from datetime import datetime,date
from zoneinfo import ZoneInfo
from unittest.mock import patch
import frappe
from qcmc_logic import dynamic_reorder_scheduler as s

def run():
    assert frappe.local.site=="erp.qcstyro.local" and frappe.session.user=="Administrator"
    actual=frappe.get_single(s.SETTINGS)
    assert actual.enabled and actual.preview_only and not actual.automatic_update_enabled
    assert not frappe.db.count(s.EXECUTION),"Use a clean local execution history; do not delete existing records"
    settings=frappe._dict(enabled=1,preview_only=0,automatic_update_enabled=1,first_scheduled_date=date(2026,12,1))
    schedule=frappe._dict(enabled=1,frequency="Monthly",execution_weekday="Monday",day_of_month=1,execution_time="02:00:00",maximum_retry_attempts=3,recover_missed_executions=1,effective_from=date(2026,12,1))
    zone=ZoneInfo("Asia/Manila")
    output=[]
    try:
        with patch.object(s,"get_schedule",return_value=schedule),patch.object(frappe,"get_single",return_value=settings),patch.object(frappe.db,"commit"),patch.object(s,"notify_run"),patch.object(s,"safe_notify") as notify,patch.object(s,"process_month",return_value={"status":"Completed","failed":0}) as process,patch.object(s,"business_now") as clock:
            clock.return_value=datetime(2026,12,1,1,59,tzinfo=zone)
            assert s.monthly()["status"]=="Awaiting First Schedule"
            process.assert_not_called()
            clock.return_value=datetime(2027,2,3,10,tzinfo=zone)
            result=s.monthly()
            assert result["status"]=="Completed" and result["catch_up"]
            effective,as_of=process.call_args.args
            assert as_of==date(2027,2,1) and effective.preview_only and not effective.automatic_update_enabled
            assert frappe.db.count(s.EXECUTION,{"status":"Missed - Superseded"})==2
            output.append("PASS: latest month recovered; two missed months audited; updates blocked")
            assert s.monthly()["status"]=="Completed"
            assert process.call_count==1
            output.append("PASS: persisted completion prevents duplicate execution")
            clock.return_value=datetime(2027,3,1,2,0,tzinfo=zone)
            process.return_value={"status":"Completed with Errors","failed":1}
            assert s.monthly()["status"]=="Retry Pending"
            assert s.monthly()["status"]=="Retry Pending"
            assert s.monthly()["status"]=="Failed - Review Required"
            calls=process.call_count
            assert s.monthly()["status"]=="Failed - Review Required"
            assert process.call_count==calls
            events=[call.args[1] for call in notify.call_args_list]
            assert events==["superseded","catch_up","retry","retry","failed"],events
            output.append("PASS: three attempts maximum; persistent terminal failure")
            output.append("PASS: scheduler dispatches consolidated events without duplicate completed alerts")
    finally:
        frappe.db.rollback()
    assert not frappe.db.count(s.EXECUTION)
    output.append("PASS: execution test records rolled back")
    return output
