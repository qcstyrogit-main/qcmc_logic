"""Monthly scheduler: calendar-month snapshots, isolated failures and idempotent processing."""
import frappe
from qcmc_logic.dynamic_reorder_clock import business_now
from qcmc_logic.dynamic_reorder_audit import record, apply_one, SETTINGS, HISTORY, key
from qcmc_logic.dynamic_reorder_service import preview_rows
from qcmc_logic.dynamic_reorder_notifications import safe_notify

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
    from frappe.utils import getdate, now_datetime
    if not frappe.db.exists("DocType", SETTINGS) or not frappe.db.exists("DocType", EXECUTION):
        return {"status":"Not Installed"}
    settings=frappe.get_single(SETTINGS)
    if not settings.enabled:
        return {"status":"Disabled"}
    if frappe.session.user!="Administrator":
        frappe.throw("Scheduler requires Administrator",frappe.PermissionError)
    now=business_now()
    as_of=due_date(now)
    # Never backfill months preceding the first configured deployment.
    lock=frappe.cache.lock("qcmc_dynamic_reorder_monthly",timeout=7200)
    if not lock.acquire(blocking=False):
        return {"status":"Already Running"}
    try:
        last=frappe.get_all(EXECUTION,fields=["scheduled_date"],order_by="scheduled_date desc",limit_page_length=1)
        baseline=settings.get("first_scheduled_date")
        if not baseline or as_of<getdate(baseline):
            return {"status":"Awaiting First Schedule"}
        superseded=0
        if not last:
            missed=getdate(baseline)
            while missed<as_of:
                frappe.get_doc(dict(doctype=EXECUTION,scheduled_date=missed,status="Missed - Superseded",details="Only latest due month is processed")).insert(ignore_permissions=True)
                superseded+=1
                missed=next_month(missed)
        elif getdate(last[0].scheduled_date)>as_of:
            return {"status":"Outside Schedule"}
        else:
            missed=next_month(getdate(last[0].scheduled_date))
            while missed<as_of:
                if not frappe.db.exists(EXECUTION,{"scheduled_date":missed}):
                    frappe.get_doc(dict(doctype=EXECUTION,scheduled_date=missed,status="Missed - Superseded",details="Only latest due month is processed")).insert(ignore_permissions=True)
                    superseded+=1
                missed=next_month(missed)
        for prior in frappe.get_all(EXECUTION,filters={"scheduled_date":["<",as_of],"status":["in",["Pending","Running","Retry Pending"]]},pluck="name"):
            frappe.db.set_value(EXECUTION,prior,{"status":"Missed - Superseded","finished_at":now_datetime()})
            superseded+=1
        name=frappe.db.get_value(EXECUTION,{"scheduled_date":as_of},"name")
        catch_up=not(now.day==1 and now.hour==2 and now.date()==as_of)
        if name:
            run=frappe.get_doc(EXECUTION,name)
            if run.status in ("Completed","Missed - Superseded","Failed - Review Required"):
                frappe.db.commit()
                return {"status":run.status}
            if run.attempts>=MAX_ATTEMPTS:
                frappe.db.set_value(EXECUTION,name,{"status":"Failed - Review Required","finished_at":now_datetime()})
                notify_run(name,"Retry limit exhausted; review calculation history and Error Log.")
                safe_notify(name,"failed")
                frappe.db.commit()
                return {"status":"Failed - Review Required"}
            catch_up=True
        else:
            run=frappe.get_doc(dict(doctype=EXECUTION,scheduled_date=as_of,status="Pending",attempts=0,catch_up=int(catch_up))).insert(ignore_permissions=True)
            name=run.name
        frappe.db.set_value(EXECUTION,name,{"status":"Running","attempts":int(run.attempts or 0)+1,"catch_up":int(catch_up),"started_at":now_datetime()})
        frappe.db.commit()
        # Catch-up/retries may never automatically apply historical recommendations.
        effective=frappe._dict(settings.as_dict() if hasattr(settings,"as_dict") and callable(settings.as_dict) else dict(settings))
        if catch_up:
            effective.preview_only=1
            effective.automatic_update_enabled=0
        try:
            result=process_month(effective,as_of)
        except Exception:
            frappe.db.rollback()
            result={"status":"Completed with Errors","failed":1,"error":frappe.get_traceback()}
        failed=bool(result.get("failed"))
        terminal=failed and int(run.attempts or 0)+1>=MAX_ATTEMPTS
        status="Failed - Review Required" if terminal else ("Retry Pending" if failed else "Completed")
        frappe.db.set_value(EXECUTION,name,{"status":status,"finished_at":now_datetime(),"details":frappe.as_json(result),"last_error":("Review Error Log and failed calculation history" if failed else "")})
        if terminal or (catch_up and not failed):
            notify_run(name, "Retry limit exhausted; manual review required" if terminal else "Missed monthly run recovered in preview-only mode")
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
    """Called by monthly() under the scheduler lock. Not a public API."""
    counts=dict(status="Completed",recorded=0,duplicates=0,applied=0,review=0,failed=0)
    for company in frappe.get_all("Reorder Policy Mapping",filters={"enabled":1},pluck="company",distinct=True):
        warehouses=frappe.get_all("Warehouse",filters={"company":company,"disabled":0,"is_group":0},pluck="name")
        for warehouse in warehouses:
            batch=key("monthly",str(as_of),company,warehouse)
            frappe.db.savepoint("dynamic_reorder_warehouse")
            try:
                rows=preview_rows(company,warehouse,as_of=as_of,period_method="Complete Calendar Months")
            except Exception:
                frappe.db.rollback(save_point="dynamic_reorder_warehouse")
                counts["failed"]+=1
                frappe.log_error(title="Dynamic Reorder warehouse calculation failed")
                frappe.db.commit()
                continue
            for row in rows:
                row.setdefault("company",company)
                ident=key(batch,row["item_code"],row["warehouse"])
                frappe.db.savepoint("dynamic_reorder_row")
                try:
                    existing=frappe.db.get_value(HISTORY,{"calculation_key":ident},["name","status"],as_dict=True)
                    if existing:
                        if existing.status=="Failed":
                            if row.get("status")=="Failed":
                                counts["failed"]+=1
                                continue
                            # Preserve original failure and recover in a separate deterministic history.
                            retry_batch=key(batch,"recovery")
                            recovery=frappe.db.exists(HISTORY,{"calculation_key":key(retry_batch,row["item_code"],row["warehouse"])})
                            if recovery:
                                counts["duplicates"]+=1
                                continue
                            name=record(row,retry_batch,as_of)
                        else:
                            counts["duplicates"]+=1
                            continue
                    else:
                        name=record(row,batch,as_of)
                except Exception:
                    frappe.db.rollback(save_point="dynamic_reorder_row")
                    counts["failed"]+=1
                    frappe.log_error(title="Dynamic Reorder history creation failed")
                    continue
                counts["recorded"]+=1
                if row.get("status")=="Failed":
                    counts["failed"]+=1
                    continue
                if row.get("status") in ("Pending Approval","New Reorder Configuration"):
                    counts["review"]+=1
                if not settings.preview_only and settings.automatic_update_enabled and row.get("status")=="Preview":
                    frappe.db.savepoint("dynamic_reorder_apply")
                    try:
                        if apply_one(name,automatic=True):
                            counts["applied"]+=1
                        else:
                            counts["review"]+=1
                    except Exception:
                        frappe.db.rollback(save_point="dynamic_reorder_apply")
                        frappe.db.set_value(HISTORY,name,{"status":"Pending Approval","reason":"Automatic application failed; review Error Log and generate a fresh preview."})
                        counts["failed"]+=1
                        counts["review"]+=1
                        frappe.log_error(title="Dynamic Reorder automatic application failed")
            frappe.db.commit()
    if counts["failed"]:
        counts["status"]="Completed with Errors"
    return counts

