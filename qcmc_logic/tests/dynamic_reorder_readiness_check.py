"""Local readiness check: real automatic application with simulated historical demand."""
from contextlib import ExitStack
from decimal import Decimal
from unittest.mock import patch
import frappe
from datetime import timedelta
from qcmc_logic.dynamic_reorder_clock import business_date
from qcmc_logic import dynamic_reorder_audit as audit
from qcmc_logic import dynamic_reorder_service as service
from qcmc_logic import dynamic_reorder_permissions as permissions

def run():
    if frappe.local.site!="erp.qcstyro.local" or frappe.session.user!="Administrator":
        frappe.throw("Local Administrator only")
    settings=frappe.get_single(audit.SETTINGS)
    assert settings.enabled and settings.preview_only and not settings.automatic_update_enabled and not settings.allow_new_reorder_rows
    company,warehouse,item_code="QC Styropackaging Corporation","FG - Sta Clara","EIEHB1BL50"
    assert not frappe.db.exists("Item Reorder",{"parent":item_code})
    existing=service.preview_rows(company,warehouse,item_code=item_code,as_of=business_date(),period_method="Rolling Days",rolling_days=90)
    assert len(existing)==1 and existing[0].get("policy")
    policy=existing[0]["policy"]
    policy_before=frappe.db.get_value("Reorder Policy",policy,["automatic_update_enabled","approval_required","seasonal_profile","increase_limit","decrease_limit"],as_dict=True)
    as_of=business_date()
    results=[]
    job=frappe.db.get_value("Scheduled Job Type",{"method":"qcmc_logic.dynamic_reorder_scheduler.monthly"},["frequency","cron_format","stopped"],as_dict=True)
    assert job and job.frequency=="Cron" and job.cron_format=="*/15 * * * *", job
    results.append("PASS: scheduler registered; cron "+job.cron_format+"; stopped="+str(job.stopped)+"; site timezone="+str(frappe.db.get_single_value("System Settings","time_zone")))
    assert permissions.query("Administrator")=="" and permissions.query("Guest")=="1=0"
    assert permissions.has_permission(None,user="Administrator") and not permissions.has_permission(None,user="Guest")
    original_user=frappe.session.user
    try:
        frappe.session.user="Guest"
        try:
            service.preview_rows(company,warehouse,item_code=item_code)
        except frappe.PermissionError:
            pass
        else:
            raise AssertionError("Unauthorized preview allowed")
    finally:
        frappe.session.user=original_user
    results.append("PASS: permission helpers and non-Administrator preview rejection")
    original_get_single=frappe.get_single
    def test_settings(doctype,*args,**kwargs):
        if doctype==audit.SETTINGS:
            return frappe._dict(enabled=1,preview_only=0,automatic_update_enabled=1,allow_new_reorder_rows=0)
        return original_get_single(doctype,*args,**kwargs)
    def forbid_commit(*args,**kwargs):
        raise RuntimeError("Commit forbidden")
    def demand(company,warehouses,items,start,end,deduct_returns=True):
        from qcmc_logic.dynamic_reorder_calculation import demand_period
        return {(item_code,warehouse,m):{"gross":Decimal(3000),"returns":Decimal(0),"net":Decimal(3000)}
                for m,_ in demand_period(as_of,"Complete Calendar Months",3,90)}
    history=None
    try:
        with ExitStack() as stack:
            stack.enter_context(patch.object(frappe.db,"commit",side_effect=forbid_commit))
            stack.enter_context(patch.object(frappe,"get_single",side_effect=test_settings))
            stack.enter_context(patch.object(frappe,"sendmail",return_value=None))
            stack.enter_context(patch.object(frappe,"enqueue",return_value=None))
            stack.enter_context(patch.object(frappe,"publish_realtime",return_value=None))
            stack.enter_context(patch.object(service,"monthly_demand",side_effect=demand))
            frappe.db.set_value("Reorder Policy",policy,{"automatic_update_enabled":1,"approval_required":0,"seasonal_profile":None,"increase_limit":30,"decrease_limit":20},update_modified=False)
            item=frappe.get_doc("Item",item_code)
            child=item.append("reorder_levels",{"warehouse":warehouse,"material_request_type":"Manufacture","warehouse_reorder_level":1100,"warehouse_reorder_qty":1400})
            item.save()
            original_level,original_qty=child.warehouse_reorder_level,child.warehouse_reorder_qty
            rows=service.preview_rows(company,warehouse,item_code=item_code,as_of=as_of,period_method="Complete Calendar Months")
            assert len(rows)==1 and rows[0]["status"]=="Preview", rows
            history=audit.record(rows[0],frappe.generate_hash(length=24),as_of)
            stale=audit.record(rows[0],frappe.generate_hash(length=24),as_of-timedelta(days=1))
            try:
                audit.apply_one(stale,automatic=True)
            except frappe.ValidationError as exc:
                assert "current-date preview" in str(exc)
            else:
                raise AssertionError("Historical recommendation accepted")
            assert frappe.db.get_value(audit.HISTORY,stale,"status")=="Preview"
            results.append("PASS: historical recommendation blocked")
            frappe.db.set_value("Reorder Policy",policy,"approval_required",1,update_modified=False)
            assert audit.apply_one(history,automatic=True) is False
            assert frappe.db.get_value(audit.HISTORY,history,"status")=="Preview"
            results.append("PASS: policy approval requirement blocks actual automatic application")
            frappe.db.set_value("Reorder Policy",policy,"approval_required",0,update_modified=False)
            assert audit.apply_one(history,automatic=True) is True
            h=frappe.get_doc(audit.HISTORY,history)
            assert h.status=="Automatically Applied" and not h.created_reorder_row
            saved=frappe.get_doc("Item Reorder",child.name)
            assert saved.warehouse_reorder_level==h.recommended_level and saved.warehouse_reorder_qty==h.recommended_qty
            results.append("PASS: real automatic application updated existing Item Reorder values")
            assert audit.rollback(history) is True
            restored=frappe.get_doc("Item Reorder",child.name)
            assert restored.warehouse_reorder_level==original_level and restored.warehouse_reorder_qty==original_qty
            results.append("PASS: rollback restored existing row values")
    finally:
        frappe.db.rollback()
        frappe.clear_document_cache("Item",item_code)
        frappe.clear_document_cache("Reorder Policy",policy)
    assert not frappe.db.exists("Item Reorder",{"parent":item_code})
    assert not history or not frappe.db.exists(audit.HISTORY,history)
    assert not frappe.db.exists(audit.HISTORY,stale)
    assert frappe.db.get_value("Reorder Policy",policy,list(policy_before),as_dict=True)==policy_before
    results.append("PASS: all temporary data restored")
    return results
