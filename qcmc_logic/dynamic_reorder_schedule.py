"""Calendar schedule helpers and Administrator-only configuration."""
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

SCHEDULE = "Reorder Schedule Settings"
WEEKDAYS = ("Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday")
ZONE = ZoneInfo("Asia/Manila")
TERMINAL = ("Completed","Missed - Superseded","Failed - Review Required")

def parse_time(value):
    if isinstance(value, timedelta):
        seconds = value.total_seconds()
        if not 0 <= seconds < 86400:
            raise ValueError("Execution time must be within one day")
        return time(int(seconds)//3600, int(seconds)%3600//60, int(seconds)%60)
    if isinstance(value, time):
        return value.replace(tzinfo=None)
    return time.fromisoformat(str(value))

def schedule_values(doc):
    frequency = doc.get("frequency") or "Monthly"
    weekday = doc.get("execution_weekday") or "Monday"
    day = int(doc.get("day_of_month") if doc.get("day_of_month") is not None else 1)
    clock = parse_time(doc.get("execution_time") or "02:00:00")
    retries = int(doc.get("maximum_retry_attempts") or 0)
    if frequency not in ("Daily","Weekly","Monthly") or weekday not in WEEKDAYS:
        raise ValueError("Invalid execution frequency or weekday")
    if not 1 <= day <= 28 or not 1 <= retries <= 10:
        raise ValueError("Day of month must be 1–28 and maximum attempts 1–10")
    if clock.second or clock.microsecond or clock.tzinfo:
        raise ValueError("Execution time must use HH:MM in Philippine time")
    return frequency, weekday, day, clock, retries

def is_slot(day, config):
    frequency, weekday, monthday, _, _ = config
    return frequency == "Daily" or (frequency == "Weekly" and day.weekday() == WEEKDAYS.index(weekday)) or (frequency == "Monthly" and day.day == monthday)

def slot_time(day, config):
    return datetime.combine(day, config[3], tzinfo=ZONE)

def latest_due(now, config):
    now = now.astimezone(ZONE)
    day = now.date()
    while not is_slot(day, config) or slot_time(day, config) > now:
        day -= timedelta(days=1)
    return day

def next_slot(now, config):
    now = now.astimezone(ZONE)
    day = now.date()
    while not is_slot(day, config) or slot_time(day, config) <= now:
        day += timedelta(days=1)
    return day

def following_slot(day, config):
    day += timedelta(days=1)
    while not is_slot(day, config):
        day += timedelta(days=1)
    return day

def get_schedule():
    import frappe
    if not frappe.db.exists("DocType", SCHEDULE):
        return None
    return frappe.get_single(SCHEDULE)

def validate(doc, method=None):
    import frappe
    from frappe.utils import getdate
    from qcmc_logic.dynamic_reorder_clock import business_now
    if frappe.session.user != "Administrator":
        frappe.throw("Only Administrator can configure reorder schedules", frappe.PermissionError)
    try:
        config = schedule_values(doc)
    except (ValueError, TypeError) as exc:
        frappe.throw(str(exc))
    old = doc.get_doc_before_save()
    # Changes start at the next future slot; never invent retroactive runs.
    changed = not old or any(str(doc.get(k)) != str(old.get(k)) for k in
        ("enabled","frequency","execution_weekday","day_of_month","execution_time"))
    if changed or not doc.get("effective_from"):
        doc.effective_from = next_slot(business_now(),config)
    else:
        doc.effective_from = getdate(old.effective_from)

def initialize():
    """Preserve existing monthly baseline during the one-time schema upgrade."""
    import frappe
    from frappe.utils import getdate
    from qcmc_logic.dynamic_reorder_clock import business_now
    if frappe.db.get_single_value(SCHEDULE,"effective_from"):
        return
    legacy = frappe.db.get_single_value("Reorder Settings","first_scheduled_date")
    config = ("Monthly","Monday",1,time(2),3)
    values = dict(enabled=1,frequency="Monthly",execution_weekday="Monday",day_of_month=1,
        execution_time="02:00:00",maximum_retry_attempts=3,recover_missed_executions=1,
        effective_from=getdate(legacy) if legacy else next_slot(business_now(),config))
    for k,v in values.items():
        frappe.db.set_single_value(SCHEDULE,k,v)
    frappe.clear_cache(doctype=SCHEDULE)

def schedule_summary():
    import frappe
    from frappe.utils import getdate
    from qcmc_logic.dynamic_reorder_clock import business_now
    if frappe.session.user != "Administrator":
        frappe.throw("Administrator required",frappe.PermissionError)
    doc=get_schedule()
    config=schedule_values(doc)
    now=business_now()
    upcoming=max(next_slot(now,config),getdate(doc.effective_from))
    last=frappe.get_all("Reorder Execution History",fields=["scheduled_date","status","finished_at"],order_by="scheduled_date desc",limit_page_length=1)
    enabled=bool(doc.enabled and frappe.db.get_single_value("Reorder Settings","enabled"))
    return dict(status="Configured / Enabled" if enabled else "Disabled",
        next_execution=str(slot_time(upcoming,config)) if enabled else None,
        last_execution=last[0] if last else None)

# Decorate only when the Frappe runtime is available (pure calendar tests need no database).
try:
    import frappe
except ImportError:
    pass
else:
    schedule_summary=frappe.whitelist(methods=["GET"])(schedule_summary)

def set_execution_key(doc, method=None):
    from frappe.utils import getdate
    if doc.scheduled_date:
        doc.execution_key = getdate(doc.scheduled_date).isoformat()

def backfill_execution_keys():
    import frappe
    from frappe.utils import getdate
    seen=set()
    rows=frappe.get_all("Reorder Execution History",fields=["name","scheduled_date","execution_key"])
    for row in rows:
        key=getdate(row.scheduled_date).isoformat()
        if key in seen:
            frappe.throw("Duplicate scheduled date in Reorder Execution History: "+key+". Review existing records before migration.")
        seen.add(key)
    for row in rows:
        key=getdate(row.scheduled_date).isoformat()
        if row.execution_key != key:
            frappe.db.set_value("Reorder Execution History",row.name,"execution_key",key,update_modified=False)

