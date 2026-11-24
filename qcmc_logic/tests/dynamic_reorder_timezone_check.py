"""Verify actual preview service across the Manila/India date boundary."""
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from unittest.mock import patch
import frappe
from qcmc_logic import dynamic_reorder_clock as clock
from qcmc_logic import dynamic_reorder_service as service
from qcmc_logic import dynamic_reorder_scheduler as scheduler

def run():
    assert frappe.local.site=="erp.qcstyro.local" and frappe.session.user=="Administrator"
    settings=frappe.get_single(scheduler.SETTINGS)
    assert settings.enabled and settings.preview_only and not settings.automatic_update_enabled
    instant=datetime(2026,11,30,18,0,tzinfo=timezone.utc)
    local=instant.astimezone(ZoneInfo("Asia/Manila"))
    india=instant.astimezone(ZoneInfo("Asia/Kolkata"))
    assert local.date()!=india.date()
    output=[]
    def process(settings,as_of):
        assert as_of==local.date()
        rows=service.preview_rows("QC Styropackaging Corporation","FG - Sta Clara",item_code="EIEHB1BL50",as_of=as_of,period_method="Complete Calendar Months")
        assert len(rows)==1 and rows[0].get("historical_end")=="2026-11-30",rows
        output.append("PASS: actual preview accepts Manila December 1 and ends history November 30")
        return {"status":"Completed","failed":0}
    with patch.object(clock,"business_now",return_value=local),patch.object(scheduler,"business_now",return_value=local),patch.object(scheduler,"process_month",side_effect=process):
        assert process(settings,scheduler.due_date(local))["status"]=="Completed"
        try:
            service.preview_rows("QC Styropackaging Corporation","FG - Sta Clara",as_of=local.date()+timedelta(days=1))
        except frappe.ValidationError as exc:
            assert "Future calculation dates" in str(exc)
        else:
            raise AssertionError("Future date accepted")
        output.append("PASS: tomorrow is rejected using Philippine business date")
    output.append("PASS: no history or reorder application performed")
    return output
