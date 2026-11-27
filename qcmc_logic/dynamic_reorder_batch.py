"""Compact calculation batches; individual history is materialized only at approval."""
import frappe
from frappe.utils import cint, getdate
from qcmc_logic.dynamic_reorder_service import require_admin, preview_rows, load_mapping
from qcmc_logic.dynamic_reorder_clock import business_date
from qcmc_logic.dynamic_reorder_calculation import number

BATCH = "Reorder Calculation Batch"
RESULT = "Reorder Calculation Item"
REVIEW = ("Preview","Pending Approval","New Reorder Configuration")


def storage_number(value):
    # Frappe Float columns are NOT NULL. The original nullable values stay in snapshot.
    return number(value) if value is not None else 0


def classify(row):
    status = row.get("status")
    if status not in REVIEW:
        return status or "Failed"
    if row.get("production_mode") != "Make to Stock":
        return "Make to Order"
    if row.get("legacy_reorder_rows"):
        return "Review Required"
    if any(row.get(k) is None for k in ("previous_level","previous_qty","reorder_level","reorder_qty")):
        return "Review Required"
    if row.get("new_reorder_row") or not row.get("reorder_row"):
        return "New Configuration"
    if number(row["previous_level"])==number(row["reorder_level"]) and number(row["previous_qty"])==number(row["reorder_qty"]):
        return "Unchanged"
    return "Pending Approval"


def create_batch(company,mapping,as_of,trigger="Manual",name=None,**filters):
    config,_=load_mapping(company,mapping,as_of)
    name=name or frappe.generate_hash(length=24)
    if frappe.db.exists(BATCH,name):
        return frappe.get_doc(BATCH,name)
    doc=frappe.get_doc(dict(doctype=BATCH,name=name,company=company,mapping=mapping,
        calculation_date=as_of,warehouse=config.replenishment_warehouse,trigger_type=trigger,
        display_title=(str(config.mapping_name or mapping)+" | "+str(as_of)+" | "+trigger)[:140],
        calculated_by=frappe.session.user,status="Queued",parameters=frappe.as_json(filters)))
    doc.insert(ignore_permissions=True,set_name=name)
    return doc


def populate(name):
    """One transaction for results; no Item Master or Material Request changes."""
    if frappe.session.user!="Administrator":
        frappe.throw("Administrator access required",frappe.PermissionError)
    doc=frappe.get_doc(BATCH,name,for_update=True)
    if doc.status not in ("Queued","Failed"):
        return dict(batch=name,status=doc.status,total=doc.total_items)
    # Failed transactions leave no partial results; do not overwrite any persisted approvals.
    if frappe.db.exists(RESULT,{"batch":name}):
        frappe.throw("Existing batch results require review")
    frappe.db.set_value(BATCH,name,"status","Running")
    rows=preview_rows(doc.company,mapping=doc.mapping,as_of=doc.calculation_date,**frappe.parse_json(doc.parameters or "{}"))
    from qcmc_logic.dynamic_reorder_audit import key
    from frappe.utils import now_datetime
    columns=["name","creation","modified","modified_by","owner","docstatus","idx","batch","item_code","status",
             "previous_level","previous_qty","recommended_level","recommended_qty","projected_qty","reason","snapshot"]
    counts=dict(total_items=0,pending_items=0,unchanged_items=0,review_items=0,failed_items=0,approved_items=0)
    values=[]
    stamp=now_datetime()
    for row in rows:
        status=classify(row)
        counts["total_items"]+=1
        bucket=("pending_items" if status in ("Pending Approval","New Configuration") else
                "unchanged_items" if status=="Unchanged" else "failed_items" if status=="Failed" else "review_items")
        counts[bucket]+=1
        values.append((key(name,row["item_code"]),stamp,stamp,"Administrator","Administrator",0,0,name,row["item_code"],status,
            storage_number(row.get("previous_level")),storage_number(row.get("previous_qty")),
            storage_number(row.get("reorder_level")),storage_number(row.get("reorder_qty")),
            storage_number(row.get("projected_qty")),row.get("reason") or "",frappe.as_json(row)))
        if len(values)>=250:
            frappe.db.bulk_insert(RESULT,fields=columns,values=values)
            values=[]
    if values:
        frappe.db.bulk_insert(RESULT,fields=columns,values=values)
    frappe.db.set_value(BATCH,name,dict(**counts,status="Pending Review" if counts["pending_items"] else "Completed",last_error=""))
    return dict(batch=name,**counts,status="Pending Review" if counts["pending_items"] else "Completed")


def background_populate(name):
    try:
        populate(name)
        frappe.db.commit()
    except Exception:
        frappe.db.rollback()
        frappe.db.set_value(BATCH,name,dict(status="Failed",last_error="Calculation failed. Review Error Log."))
        frappe.log_error(title="Reorder batch calculation failed: "+name)
        frappe.db.commit()


@frappe.whitelist(methods=["POST"])
def start(company,mapping,item_code=None,item_group=None,as_of=None,period_method=None,rolling_days=None):
    require_admin()
    day=getdate(as_of or business_date())
    if day>business_date():
        frappe.throw("Future calculation dates are not supported")
    if period_method not in (None,"","Complete Calendar Months","Rolling Days","Month-to-Date Inclusive"):
        frappe.throw("Invalid demand period")
    days=cint(rolling_days) if period_method=="Rolling Days" else None
    if period_method=="Rolling Days" and not 1<=days<=1096:
        frappe.throw("Rolling Days must be between 1 and 1096")
    doc=create_batch(company,mapping,day,item_code=item_code or None,item_group=item_group or None,
        period_method=period_method or None,rolling_days=days)
    frappe.enqueue(background_populate,queue="long",timeout=3600,enqueue_after_commit=True,name=doc.name)
    return dict(batch=doc.name,status="Queued")


@frappe.whitelist(methods=["GET"])
def page(batch,offset=0,limit=50,status=None,search=None):
    if frappe.session.user!="Administrator":
        frappe.throw("Administrator access required",frappe.PermissionError)
    doc=frappe.get_doc(BATCH,batch)
    filters={"batch":batch}
    if status:
        filters["status"]=status
    if search:
        filters["item_code"]=["like","%"+str(search)[:100]+"%"]
    offset=max(0,cint(offset)); limit=max(1,min(100,cint(limit) or 50))
    rows=frappe.get_all(RESULT,filters=filters,fields=["name","item_code","status","previous_level","previous_qty",
        "recommended_level","recommended_qty","projected_qty","reason","approval_history"],
        order_by="item_code asc",limit_start=offset,limit_page_length=limit)
    return dict(rows=rows,total=frappe.db.count(RESULT,filters),status=doc.status)


@frappe.whitelist(methods=["POST"])
def approve(batch,items):
    require_admin()
    from qcmc_logic.dynamic_reorder_audit import record, apply_one
    items=frappe.parse_json(items) if isinstance(items,str) else items
    if not isinstance(items,list) or not items or len(items)>50 or any(not isinstance(i,str) for i in items):
        frappe.throw("Select between 1 and 50 items")
    doc=frappe.get_doc(BATCH,batch,for_update=True)
    if doc.status not in ("Pending Review","Completed"):
        frappe.throw("Batch is not ready for review")
    results=[]
    for name in sorted(set(items)):
        frappe.db.savepoint("reorder_batch_approval")
        try:
            row=frappe.get_doc(RESULT,name,for_update=True)
            if row.batch!=batch or row.status not in ("Pending Approval","New Configuration"):
                frappe.throw("Item is not eligible for approval")
            snapshot=frappe.parse_json(row.snapshot)
            if snapshot.get("item_code")!=row.item_code or snapshot.get("mapping")!=doc.mapping or snapshot.get("company")!=doc.company:
                frappe.throw("Batch snapshot scope mismatch")
            history=record(snapshot,batch,doc.calculation_date)
            apply_one(history)
            frappe.db.set_value(RESULT,name,dict(status="Approved",approval_history=history))
            results.append(dict(item=row.item_code,status="Approved"))
        except frappe.ValidationError as exc:
            frappe.db.rollback(save_point="reorder_batch_approval")
            frappe.clear_messages()
            results.append(dict(item=name,status="Blocked",reason=str(exc)))
    refresh_counts(batch)
    return results


def refresh_counts(batch):
    """Recompute mutable summary after approval or rollback, under the batch lock."""
    pending=frappe.db.count(RESULT,{"batch":batch,"status":["in",["Pending Approval","New Configuration"]]})
    approved=frappe.db.count(RESULT,{"batch":batch,"status":"Approved"})
    reverted=frappe.db.count(RESULT,{"batch":batch,"status":"Reverted"})
    frappe.db.set_value(BATCH,batch,dict(pending_items=pending,approved_items=approved,reverted_items=reverted,
        status="Pending Review" if pending else "Completed"))
