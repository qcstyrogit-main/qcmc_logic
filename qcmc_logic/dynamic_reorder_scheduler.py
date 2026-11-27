"""Monthly scheduler: calendar-month snapshots, isolated failures and idempotent processing."""
import frappe
from qcmc_logic.dynamic_reorder_clock import business_now
from qcmc_logic.dynamic_reorder_audit import record, apply_one, SETTINGS, HISTORY, key, calculation_identity
from qcmc_logic.dynamic_reorder_service import preview_rows
from qcmc_logic.dynamic_reorder_notifications import safe_notify
from qcmc_logic.dynamic_reorder_schedule import get_schedule, schedule_values, latest_due, following_slot, slot_time

EXECUTION = "Reorder Execution History"
MAX_ATTEMPTS = 3

def due_date(now):
    from datetime import timedelta
    first=now.date().replace(day=1)
    if now.day==1 and now.hour<2:
        return (first-timedelta(days=1)).replace(day=1)
    return first

def next_month(day):
    from datetime import timedelta
    return (day.replace(day=28)+timedelta(days=4)).replace(day=1)

def notify_run(name, message):
    # A durable Error Log is visible to administrators; no email configuration assumed.
    frappe.log_error(message=message,title="Reorder scheduler: "+name)

def monthly():
    """Compatibility entry point for the existing 15-minute cron."""
    from frappe.utils import getdate, now_datetime
    if not frappe.db.exists("DocType", SETTINGS) or not frappe.db.exists("DocType", EXECUTION):
        return {"status":"Not Installed"}
    if frappe.session.user!="Administrator":
        frappe.throw("Scheduler requires Administrator",frappe.PermissionError)
    lock=frappe.cache.lock("qcmc_dynamic_reorder_monthly",timeout=7200)
    if not lock.acquire(blocking=False):
        return {"status":"Already Running"}
    try:
        settings=frappe.get_single(SETTINGS)
        schedule=get_schedule()
        if not settings.enabled or not schedule or not schedule.enabled:
            return {"status":"Disabled"}
        config=schedule_values(schedule)
        max_attempts=config[4]
        now=business_now()
        as_of=latest_due(now,config)
        baseline=schedule.get("effective_from")
        if not baseline or as_of<getdate(baseline):
            return {"status":"Awaiting First Schedule"}
        baseline=getdate(baseline)
        last=frappe.get_all(EXECUTION,fields=["scheduled_date"],order_by="scheduled_date desc",limit_page_length=1)
        if last and getdate(last[0].scheduled_date)>as_of:
            return {"status":"Outside Schedule"}
        missed=max(baseline,following_slot(getdate(last[0].scheduled_date),config)) if last else baseline
        superseded=0
        while missed<as_of:
            if not frappe.db.exists(EXECUTION,{"scheduled_date":missed}):
                frappe.get_doc(dict(doctype=EXECUTION,scheduled_date=missed,status="Missed - Superseded",details="Only latest due schedule is processed")).insert(ignore_permissions=True)
                superseded+=1
            missed=following_slot(missed,config)
        for prior in frappe.get_all(EXECUTION,filters={"scheduled_date":["<",as_of],"status":["in",["Pending","Running","Retry Pending"]]},pluck="name"):
            frappe.db.set_value(EXECUTION,prior,{"status":"Missed - Superseded","finished_at":now_datetime()})
            superseded+=1
        name=frappe.db.get_value(EXECUTION,{"scheduled_date":as_of},"name")
        catch_up=(now-slot_time(as_of,config)).total_seconds()>=900
        if name:
            run=frappe.get_doc(EXECUTION,name)
            if run.status in ("Completed","Completed with Item Errors","Missed - Superseded","Failed - Review Required"):
                frappe.db.commit()
                return {"status":run.status}
            if run.attempts>=max_attempts:
                frappe.db.set_value(EXECUTION,name,{"status":"Failed - Review Required","finished_at":now_datetime()})
                notify_run(name,"Retry limit exhausted; review calculation history and Error Log.")
                safe_notify(name,"failed")
                frappe.db.commit()
                return {"status":"Failed - Review Required"}
            catch_up=True
        elif catch_up and not schedule.recover_missed_executions:
            run=frappe.get_doc(dict(doctype=EXECUTION,scheduled_date=as_of,status="Missed - Superseded",details="Missed schedule recovery disabled",catch_up=1)).insert(ignore_permissions=True)
            safe_notify(run.name,"superseded",superseded=superseded+1)
            frappe.db.commit()
            return {"status":"Missed - Superseded"}
        else:
            run=frappe.get_doc(dict(doctype=EXECUTION,scheduled_date=as_of,status="Pending",attempts=0,catch_up=int(catch_up))).insert(ignore_permissions=True)
            name=run.name
        frappe.db.set_value(EXECUTION,name,{"status":"Running","attempts":int(run.attempts or 0)+1,"catch_up":int(catch_up),"started_at":now_datetime()})
        frappe.db.commit()
        # Scheduled runs remain preview-only until a separately authorized release.
        effective=frappe._dict(settings.as_dict() if hasattr(settings,"as_dict") and callable(settings.as_dict) else dict(settings))
        effective.preview_only=1
        effective.automatic_update_enabled=0
        try:
            result=process_month(effective,as_of)
        except Exception:
            frappe.db.rollback()
            result={"status":"Completed with Errors","failed":1,"error":frappe.get_traceback()}
        failed=bool(result.get("failed"))
        terminal=failed and int(run.attempts or 0)+1>=max_attempts
        status="Failed - Review Required" if terminal else ("Retry Pending" if failed else ("Completed with Item Errors" if result.get("item_failed") else "Completed"))
        frappe.db.set_value(EXECUTION,name,{"status":status,"finished_at":now_datetime(),"details":frappe.as_json(result),"last_error":("Review Error Log and failed calculation history" if failed else "")})
        if terminal or (catch_up and not failed):
            notify_run(name,"Retry limit exhausted; manual review required" if terminal else "Missed scheduled run recovered in preview-only mode")
        if superseded:
            safe_notify(name,"superseded",result,superseded)
        if result.get("error"):
            safe_notify(name,"unexpected",result)
        if result.get("review"):
            safe_notify(name,"approval",result)
        safe_notify(name,"failed" if terminal else ("retry" if failed else ("catch_up" if catch_up else "completed")),result)
        frappe.db.commit()
        return dict(result,execution=name,status=status,catch_up=catch_up)
    finally:
        lock.release()

def process_month(settings,as_of):
    """One deterministic batch per mapping and schedule slot; never applies values."""
    from qcmc_logic.dynamic_reorder_batch import create_batch,populate,BATCH
    counts=dict(status="Completed",recorded=0,duplicates=0,applied=0,review=0,failed=0,item_failed=0,batches=[])
    mappings=frappe.get_all("Reorder Policy Mapping",filters={"enabled":1},fields=["name","company"])
    for mapping in mappings:
        batch=key("mapping-schedule-v3",str(as_of),mapping.name)
        frappe.db.savepoint("dynamic_reorder_mapping")
        try:
            doc=create_batch(mapping.company,mapping.name,as_of,trigger="Scheduled",name=batch)
            if doc.status in ("Pending Review","Completed"):
                counts["duplicates"]+=int(doc.total_items or 0)
                counts["review"]+=int(doc.pending_items or 0)
                counts["item_failed"]+=int(doc.failed_items or 0)
            else:
                result=populate(doc.name)
                counts["recorded"]+=int(result.get("total_items") or 0)
                counts["review"]+=int(result.get("pending_items") or 0)
                counts["item_failed"]+=int(result.get("failed_items") or 0)
            counts["batches"].append(doc.name)
        except Exception:
            frappe.db.rollback(save_point="dynamic_reorder_mapping")
            counts["failed"]+=1
            frappe.log_error(title="Reorder scheduled batch failed: "+mapping.name)
        frappe.db.commit()
    if counts["failed"] or counts["item_failed"]:
        counts["status"]="Completed with Errors"
    return counts

