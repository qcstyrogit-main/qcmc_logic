"""Local scheduler integration check with simulated eligibility; no committed writes."""
from unittest.mock import patch, Mock
from datetime import datetime
from zoneinfo import ZoneInfo
import frappe
from frappe.utils import getdate, nowdate
from qcmc_logic import dynamic_reorder_scheduler as scheduler
from qcmc_logic.dynamic_reorder_audit import HISTORY, SETTINGS, key

def run():
    if frappe.local.site != "erp.qcstyro.local" or frappe.session.user != "Administrator":
        frappe.throw("Local Administrator only")
    settings=frappe.get_single(SETTINGS)
    if not settings.enabled or not settings.preview_only or settings.automatic_update_enabled:
        frappe.throw("Expected safe enabled preview-only settings")
    company="QC Styropackaging Corporation"
    warehouse="FG - Sta Clara"
    item="EIEHB1BL50"
    as_of=getdate(nowdate()).replace(day=1)
    test_now=datetime(as_of.year,as_of.month,1,2,15,tzinfo=ZoneInfo("Asia/Manila"))
    batch=key("scheduler-test",frappe.generate_hash(length=24),company,warehouse)
    ident=key(batch,item,warehouse)
    real_key=scheduler.key
    real_get_all=frappe.get_all
    def scoped_get_all(doctype,*args,**kwargs):
        if doctype=="Reorder Policy Mapping" and kwargs.get("pluck")=="company":
            return [company]
        if doctype=="Warehouse" and kwargs.get("pluck")=="name":
            return [warehouse]
        return real_get_all(doctype,*args,**kwargs)
    def scoped_key(*args):
        return batch if args[0]=="monthly" else real_key(*args)
    row=dict(item_code=item,warehouse=warehouse,company=company,status="Preview",
             previous_level=100,previous_qty=200,reorder_level=110,reorder_qty=220,
             demand_period_method="Complete Calendar Months")
    results=[]
    try:
        with patch.object(scheduler,"business_now",return_value=test_now), patch.object(frappe.db,"commit",return_value=None), patch.object(frappe,"get_all",side_effect=scoped_get_all), patch.object(scheduler,"key",side_effect=scoped_key), patch.object(scheduler,"preview_rows",return_value=[row.copy()]) as preview, patch.object(scheduler,"apply_one") as apply:
            first=scheduler.process_month(settings,as_of)
            assert first["recorded"]==1 and first["applied"]==0 and first["failed"]==0, first
            preview.assert_called_once_with(company,warehouse,as_of=as_of,period_method="Complete Calendar Months")
            assert frappe.db.exists(HISTORY,{"calculation_key":ident})
            apply.assert_not_called()
            results.append("PASS: monthly calendar period, actual history insertion, preview-only protection")
            second=scheduler.process_month(settings,as_of)
            assert second["duplicates"]==1 and second["recorded"]==0, second
            apply.assert_not_called()
            results.append("PASS: same-month rerun prevented duplicate history and application")
            disabled=frappe._dict(enabled=0)
            with patch.object(frappe,"get_single",return_value=disabled):
                assert scheduler.monthly()["status"]=="Disabled"
            results.append("PASS: master disable switch")
            # Isolate a fresh test batch for the review and auto eligibility paths.
            batch=key("scheduler-test",frappe.generate_hash(length=24),company,warehouse)
            review_ident=key(batch,item,warehouse)
            preview.return_value=[dict(row,status="Pending Approval")]
            auto=frappe._dict(enabled=1,preview_only=0,automatic_update_enabled=1)
            with patch.object(frappe,"get_single",return_value=auto):
                third=scheduler.process_month(auto,as_of)
                assert third["review"]==1 and third["applied"]==0, third
                apply.assert_not_called()
            results.append("PASS: pending approval cannot be automatically applied")
            batch=key("scheduler-test",frappe.generate_hash(length=24),company,warehouse)
            auto_ident=key(batch,item,warehouse)
            preview.return_value=[row.copy()]
            apply.return_value=True
            with patch.object(frappe,"get_single",return_value=auto):
                fourth=scheduler.process_month(auto,as_of)
                assert fourth["applied"]==1, fourth
                apply.assert_called_once_with(frappe.db.get_value(HISTORY,{"calculation_key":auto_ident},"name"),automatic=True)
            results.append("PASS: eligible preview dispatched to automatic application (mocked apply)")
            batch=key("scheduler-test",frappe.generate_hash(length=24),company,warehouse)
            failure_ident=key(batch,item,warehouse)
            apply.side_effect=ValueError("simulated application failure")
            with patch.object(frappe,"get_single",return_value=auto), patch.object(frappe,"log_error") as log:
                fifth=scheduler.process_month(auto,as_of)
                assert fifth["failed"]==1 and fifth["review"]==1, fifth
                assert frappe.db.get_value(HISTORY,{"calculation_key":failure_ident},"status")=="Pending Approval"
                log.assert_called_once()
            results.append("PASS: application failure preserves history for manual review")
    finally:
        frappe.db.rollback()
    assert not frappe.db.exists(HISTORY,{"calculation_key":ident})
    assert not frappe.db.exists(HISTORY,{"calculation_key":review_ident})
    assert not frappe.db.exists(HISTORY,{"calculation_key":auto_ident})
    assert not frappe.db.exists(HISTORY,{"calculation_key":failure_ident})
    results.append("PASS: test history rolled back; no actual reorder updates")
    return results
