"""Audited preview, guarded application and rollback for existing reorder rows."""
import hashlib
import frappe
from frappe.utils import now_datetime, getdate
from qcmc_logic.dynamic_reorder_clock import business_date
from qcmc_logic.dynamic_reorder_service import preview_rows, require_admin
from qcmc_logic.dynamic_reorder_calculation import number

HISTORY = "Reorder Calculation History"
SETTINGS = "Reorder Settings"

def key(*values):
    return hashlib.sha256(frappe.as_json(values).encode()).hexdigest()

def calculation_identity(row, batch):
    # Preserve old history identities; V2 is independent of destination changes.
    return key(batch, row["item_code"], row.get("mapping") or row["warehouse"])


def record(row, batch, as_of):
    ident = calculation_identity(row,batch)
    existing = frappe.db.get_value(HISTORY, {"calculation_key":ident}, "name")
    if existing:
        return existing
    doc = frappe.get_doc(dict(doctype=HISTORY, calculation_key=ident, batch=batch,
        calculation_date=as_of, company=row.get("company"), item_code=row["item_code"],
        warehouse=row["warehouse"], mapping=row.get("mapping"), policy=row.get("policy"), reorder_row=row.get("reorder_row"),
        status=row["status"], previous_level=row.get("previous_level"), previous_qty=row.get("previous_qty"),
        recommended_level=row.get("reorder_level"), recommended_qty=row.get("reorder_qty"),
        actual_qty=row.get("actual_qty"), projected_qty=row.get("projected_qty"),
        details=frappe.as_json(row), reason=row.get("reason")))
    doc.insert(ignore_permissions=True)
    return doc.name

@frappe.whitelist(methods=["POST"])
def run_preview(company, warehouse=None, item_group=None, item_code=None, as_of=None, period_method=None, rolling_days=None, mapping=None):
    require_admin()
    as_of = getdate(as_of or business_date())
    from frappe.utils import cint
    period_method = period_method or None
    if period_method and period_method not in ("Complete Calendar Months","Rolling Days","Month-to-Date Inclusive"):
        frappe.throw("Invalid demand period method")
    if period_method == "Rolling Days":
        rolling_days = cint(rolling_days)
        if not 1 <= rolling_days <= 1096:
            frappe.throw("Rolling Days must be between 1 and 1096")
    else:
        rolling_days = None
    batch = frappe.generate_hash(length=24)
    rows = preview_rows(company,warehouse,item_group,item_code,as_of,period_method,rolling_days,mapping=mapping)
    if period_method and any(row.get("demand_period_method") and row["demand_period_method"] != period_method for row in rows):
        frappe.throw("Calculation period differs from requested method")
    for row in rows:
        row.setdefault("company",company)
        row["history_name"] = record(row,batch,as_of)
    return {"batch":batch,"rows":rows}

def locked_history(name):
    row = frappe.db.sql("SELECT name FROM `tabReorder Calculation History` WHERE name=%s FOR UPDATE",name)
    if not row: frappe.throw("Calculation history not found")
    return frappe.get_doc(HISTORY,name)

def locked_item(history):
    frappe.db.sql("SELECT name FROM `tabItem` WHERE name=%s FOR UPDATE",history.item_code)
    item=frappe.get_doc("Item",history.item_code)
    matches=[r for r in item.reorder_levels if r.warehouse==history.warehouse]
    if len(matches)!=1 or matches[0].name!=history.reorder_row or (matches[0].warehouse_group and matches[0].warehouse_group != history.warehouse):
        frappe.throw("Reorder configuration changed; generate a fresh preview")
    return item,matches[0]

PREVIEW_ONLY_REASON = "Consolidated recommendations are preview-only until ERPNext integration and duplicate-request protection are validated"


def validate_application(h, item):
    """Fail closed unless manual application is explicitly enabled and preview is fresh."""
    from frappe.utils import cint
    settings = frappe.get_single(SETTINGS)
    if not settings.enabled or settings.preview_only or settings.automatic_update_enabled:
        frappe.throw("Enable Reorder Settings, disable Preview Only and keep Automatic Update disabled for manual approval")
    # Until live native integration is verified, require native auto reorder OFF.
    if cint(frappe.db.get_single_value("Stock Settings", "auto_indent")):
        frappe.throw("Native automatic Material Requests must be disabled before manual application")
    if not h.mapping or h.status not in ("Preview","Pending Approval","New Reorder Configuration"):
        frappe.throw("Only unapplied consolidated recommendations can be approved")
    if getdate(h.calculation_date) != business_date():
        frappe.throw("Generate a fresh preview for today's calculation date")
    snap = frappe.parse_json(h.details or "{}")
    if snap.get("schema_version") != 2 or snap.get("production_mode") != "Make to Stock":
        frappe.throw("Only V2 Make to Stock recommendations can be applied")
    rows = preview_rows(h.company, mapping=h.mapping, item_code=h.item_code,
                        as_of=h.calculation_date, period_method=snap.get("demand_period_method"),
                        rolling_days=snap.get("rolling_days"))
    if len(rows) != 1 or rows[0].get("status") not in ("Preview","Pending Approval","New Reorder Configuration"):
        frappe.throw("Item is no longer eligible; generate a fresh preview")
    fresh = rows[0]
    for field in ("company","mapping","warehouse","item_code","policy","override","warehouses",
                  "production_mode","material_request_type","reorder_row","legacy_reorder_rows",
                  "period_segments","demand_sources","policy_snapshot","monthly_demand"):
        if key(snap.get(field)) != key(fresh.get(field)):
            frappe.throw("Calculation scope or inputs changed (" + field + "); generate a fresh preview")
    for field, saved in (("reorder_level",h.recommended_level),("reorder_qty",h.recommended_qty),
                         ("previous_level",h.previous_level),("previous_qty",h.previous_qty),
                         ("actual_qty",h.actual_qty),("projected_qty",h.projected_qty),
                         ("net_demand",snap.get("net_demand"))):
        if fresh.get(field) is None or saved is None or number(fresh[field]) != number(saved):
            frappe.throw("Calculation values changed or incomplete (" + field + "); generate a fresh preview")
    if fresh.get("legacy_reorder_rows"):
        frappe.throw("Conflicting unmanaged reorder rows require explicit review")
    if number(h.recommended_level)<0 or number(h.recommended_qty)<0:
        frappe.throw("Invalid negative recommendation")
    matches = [r for r in item.reorder_levels if r.get("custom_reorder_mapping")==h.mapping]
    if len(matches)>1 or bool(matches) != bool(h.reorder_row):
        frappe.throw("Managed reorder ownership changed; generate a fresh preview")
    row = matches[0] if matches else None
    if row and (row.name!=h.reorder_row or not row.custom_managed_reorder or row.warehouse!=h.warehouse or row.warehouse_group not in (None,"",h.warehouse)):
        frappe.throw("Managed reorder row changed")
    if not row and (not settings.allow_new_reorder_rows or not fresh["policy_snapshot"].get("allow_new_reorder_rows")):
        frappe.throw("Allow New Reorder Rows must be enabled in Reorder Settings and the policy")
    request_type = fresh.get("material_request_type")
    if request_type == "Preserve":
        request_type = row.material_request_type if row else None
    if request_type not in ("Manufacture","Purchase"):
        frappe.throw("Select an explicit supported Material Request Type")
    if row and row.material_request_type != request_type:
        frappe.throw("Existing request type differs; review configuration before approval")
    return row, request_type


@frappe.whitelist(methods=["POST"])
def application_precheck(name):
    require_admin()
    h = frappe.get_doc(HISTORY,name)
    try:
        validate_application(h, frappe.get_doc("Item",h.item_code))
    except frappe.ValidationError as exc:
        frappe.clear_messages()
        return dict(allowed=False,checks=[dict(ok=False,label=str(exc))],policy=h.policy,item_code=h.item_code)
    return dict(allowed=True,checks=[dict(ok=True,label="Fresh calculation and manual approval safeguards passed")],
                policy=h.policy,item_code=h.item_code)


def apply_one(name, automatic=False):
    if automatic:
        frappe.throw(PREVIEW_ONLY_REASON)
    require_admin()
    h = locked_history(name)
    frappe.db.sql("SELECT name FROM `tabCompany` WHERE name=%s FOR UPDATE", h.company)
    frappe.db.sql("SELECT name FROM `tabItem` WHERE name=%s FOR UPDATE", h.item_code)
    item = frappe.get_doc("Item",h.item_code,for_update=True)
    row, request_type = validate_application(h,item)
    created = not row
    if created:
        row = item.append("reorder_levels",dict(warehouse=h.warehouse,material_request_type=request_type,
                         custom_managed_reorder=1,custom_reorder_mapping=h.mapping))
    snapshot = frappe.parse_json(h.details)
    snapshot["previous_history"] = row.get("custom_reorder_history")
    snapshot["applied_request_type"] = request_type
    row.warehouse_reorder_level=h.recommended_level
    row.warehouse_reorder_qty=h.recommended_qty
    row.custom_reorder_history=h.name
    item.save()
    frappe.db.set_value(HISTORY,h.name,dict(status="Approved",reorder_row=row.name,
        created_reorder_row=int(created),applied_by=frappe.session.user,applied_at=now_datetime(),
        details=frappe.as_json(snapshot)))
    return {"status":"Approved","name":h.name,"reorder_row":row.name}


@frappe.whitelist(methods=["POST"])
def apply(name):
    require_admin()
    return apply_one(name)


@frappe.whitelist(methods=["POST"])
def reject(name, reason):
    """Reject an unapplied V2 calculation; never change inventory or reorder rows."""
    require_admin()
    reason = (reason or "").strip()
    if not reason or len(reason) > 1000:
        frappe.throw("Enter a rejection reason of 1 to 1000 characters")
    h = locked_history(name)
    if not h.mapping or h.status not in ("Preview", "Pending Approval", "New Reorder Configuration"):
        frappe.throw("Only unapplied consolidated recommendations may be rejected")
    previous_reason = h.reason or ""
    from frappe.utils import escape_html
    h.add_comment("Comment", "Rejected by " + escape_html(frappe.session.user) +
                  " at " + str(now_datetime()) + ": " + escape_html(reason))
    frappe.db.set_value(HISTORY, h.name, {
        "status": "Rejected",
        "reason": "Rejected: " + reason + (" | Calculation: " + previous_reason if previous_reason else "")
    })
    return {"status": "Rejected", "name": h.name}

@frappe.whitelist(methods=["POST"])
def rollback(name):
    require_admin()
    # Acquire the batch before history/item locks, matching bulk approval lock order.
    from qcmc_logic.dynamic_reorder_batch import BATCH, RESULT
    batch_row=None
    if frappe.db.exists("DocType",RESULT):
        batch_row=frappe.db.get_value(RESULT,{"approval_history":name},["name","batch"],as_dict=True)
        if batch_row:
            frappe.get_doc(BATCH,batch_row.batch,for_update=True)
            frappe.get_doc(RESULT,batch_row.name,for_update=True)
    h=locked_history(name)
    if h.status not in ("Approved","Automatically Applied"):
        frappe.throw("Only applied calculations can be reverted")
    item,row=locked_item(h)
    if number(row.warehouse_reorder_level or 0)!=number(h.recommended_level or 0) or number(row.warehouse_reorder_qty or 0)!=number(h.recommended_qty or 0):
        frappe.throw("Current values differ; manual review required")
    newer=frappe.db.exists(HISTORY,{"reorder_row":h.reorder_row,"applied_at":[">",h.applied_at],"status":["in",["Approved","Automatically Applied"]]})
    if newer: frappe.throw("A later application exists; manual review required")
    snapshot=frappe.parse_json(h.details or "{}")
    expected_type = snapshot.get("applied_request_type") or snapshot.get("material_request_type")
    if expected_type and row.material_request_type != expected_type:
        frappe.throw("Material Request Type changed; manual review required")
    if h.mapping and (not row.custom_managed_reorder or row.custom_reorder_mapping != h.mapping
                      or row.custom_reorder_history != h.name or row.warehouse_group not in (None,"",h.warehouse)):
        frappe.throw("Managed row ownership changed; manual review required")
    if h.created_reorder_row:
        item.remove(row)
    else:
        row.warehouse_reorder_level=h.previous_level
        row.warehouse_reorder_qty=h.previous_qty
        if h.mapping:
            row.custom_reorder_history=snapshot.get("previous_history")
    item.save()
    frappe.db.set_value(HISTORY,h.name,{"status":"Reverted","reason":"Reverted by "+frappe.session.user+" at "+str(now_datetime())})
    if batch_row:
        frappe.db.set_value(RESULT,batch_row.name,"status","Reverted")
        from qcmc_logic.dynamic_reorder_batch import refresh_counts
        refresh_counts(batch_row.batch)
    return True
