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

def record(row, batch, as_of):
    ident = key(batch, row["item_code"], row["warehouse"])
    existing = frappe.db.get_value(HISTORY, {"calculation_key":ident}, "name")
    if existing:
        return existing
    doc = frappe.get_doc(dict(doctype=HISTORY, calculation_key=ident, batch=batch,
        calculation_date=as_of, company=row.get("company"), item_code=row["item_code"],
        warehouse=row["warehouse"], policy=row.get("policy"), reorder_row=row.get("reorder_row"),
        status=row["status"], previous_level=row.get("previous_level"), previous_qty=row.get("previous_qty"),
        recommended_level=row.get("reorder_level"), recommended_qty=row.get("reorder_qty"),
        actual_qty=row.get("actual_qty"), projected_qty=row.get("projected_qty"),
        details=frappe.as_json(row), reason=row.get("reason")))
    doc.insert(ignore_permissions=True)
    return doc.name

@frappe.whitelist(methods=["POST"])
def run_preview(company, warehouse, item_group=None, item_code=None, as_of=None, period_method=None, rolling_days=None):
    require_admin()
    as_of = getdate(as_of or business_date())
    from frappe.utils import cint
    period_method = period_method or "Complete Calendar Months"
    if period_method not in ("Complete Calendar Months","Rolling Days","Month-to-Date Inclusive"):
        frappe.throw("Invalid demand period method")
    if period_method == "Rolling Days":
        rolling_days = cint(rolling_days)
        if not 1 <= rolling_days <= 1096:
            frappe.throw("Rolling Days must be between 1 and 1096")
    else:
        rolling_days = None
    batch = frappe.generate_hash(length=24)
    rows = preview_rows(company,warehouse,item_group,item_code,as_of,period_method,rolling_days)
    if any(row.get("demand_period_method") and row["demand_period_method"] != period_method for row in rows):
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

@frappe.whitelist(methods=["POST"])
def application_precheck(name):
    """Read-only UI guidance; apply_one remains the authoritative locked validation."""
    require_admin()
    h=frappe.get_doc(HISTORY,name)
    settings=frappe.get_single(SETTINGS)
    checks=[]
    def add(ok,label,target=None):
        checks.append(dict(ok=bool(ok),label=label,target=target))
    add(settings.enabled,"Reorder Management must be enabled","settings")
    add(not settings.preview_only,"Preview Only must be disabled","settings")
    add(h.status in ("Preview","Pending Approval","New Reorder Configuration"),"Recommendation must be awaiting application")
    add(getdate(h.calculation_date)==business_date(),"Calculation must use today's Philippine business date","preview")
    creating=h.status=="New Reorder Configuration"
    add(bool(h.policy) and (creating or bool(h.reorder_row)),"Eligible policy and reorder configuration required","preview")
    policy=frappe.get_doc("Reorder Policy",h.policy) if h.policy and frappe.db.exists("Reorder Policy",h.policy) else None
    add(bool(policy and policy.enabled),"Reorder Policy must be enabled","policy")
    snapshot=frappe.parse_json(h.details or "{}")
    if creating:
        add(settings.allow_new_reorder_rows,"Allow New Reorder Rows must be enabled in Reorder Settings","settings")
        add(bool(policy and policy.allow_new_reorder_rows),"Allow New Reorder Rows must be enabled in Reorder Policy","policy")
        request_type=policy.material_request_type if policy else None
        add(request_type in ("Manufacture","Purchase"),"Select an explicit Material Request Type (Manufacture or Purchase)","policy")
        add(request_type in ("Manufacture","Purchase") and snapshot.get("material_request_type")==request_type,"Saved preview must match the configured Material Request Type","preview")
        add(number(h.recommended_level or 0)>0 and number(h.recommended_qty or 0)>0,"Recommended level and quantity must be positive","preview")
        add(not frappe.db.exists("Item Reorder",{"parent":h.item_code,"warehouse":h.warehouse}),"No existing reorder row for this warehouse","preview")
        if request_type=="Manufacture":
            add(bool(frappe.db.exists("BOM",{"item":h.item_code,"is_active":1,"is_default":1,"docstatus":1})),"An active submitted default BOM is required","item")
        elif request_type=="Purchase":
            add(bool(frappe.db.get_value("Item",h.item_code,"is_purchase_item")),"Item must be eligible for purchase","item")
    else:
        add(bool(h.reorder_row and frappe.db.exists("Item Reorder",{"name":h.reorder_row,"parent":h.item_code,"warehouse":h.warehouse})),"Existing reorder row must still match the preview","preview")
    return dict(allowed=all(c["ok"] for c in checks),checks=checks,policy=h.policy,item_code=h.item_code)

def apply_one(name, automatic=False):
    settings=frappe.get_single(SETTINGS)
    if not settings.enabled or settings.preview_only:
        frappe.throw("Updates disabled; leave preview mode only after validation")
    h=locked_history(name)
    if h.status not in ("Preview","Pending Approval","New Reorder Configuration"):
        frappe.throw("This calculation cannot be applied")
    if automatic and (h.status!="Preview" or not settings.automatic_update_enabled):
        return False
    if getdate(h.calculation_date)!=business_date():
        frappe.throw("Generate a current-date preview before applying historical recommendations")
    creating = h.status=="New Reorder Configuration"
    if not h.policy or (not creating and not h.reorder_row):
        frappe.throw("No eligible recommendation")
    # Recalculate against current inputs before making any changes.
    snapshot=frappe.parse_json(h.details or "{}")
    method=snapshot.get("demand_period_method") or "Complete Calendar Months"
    if automatic and method!="Complete Calendar Months":
        return False
    fresh=preview_rows(h.company,h.warehouse,item_code=h.item_code,as_of=h.calculation_date,
        period_method=method,rolling_days=snapshot.get("rolling_days") if method=="Rolling Days" else None)
    eligible=[r for r in fresh if (r.get("reorder_row") or "")==(h.reorder_row or "") and r.get("status") in ("Preview","Pending Approval","New Reorder Configuration") and "reorder_level" in r and bool(r.get("new_reorder_row"))==creating]
    if len(eligible)!=1: frappe.throw("Recommendation no longer eligible")
    r=eligible[0]
    if "Maximum stock requires review" in r.get("reason",""):
        frappe.throw("Resolve maximum-stock conflict before applying")
    if snapshot.get("material_request_type") != r.get("material_request_type"):
        frappe.throw("Material Request Type changed; generate a fresh preview")
    if r["policy"]!=h.policy or number(r["reorder_level"])!=number(h.recommended_level) or number(r["reorder_qty"])!=number(h.recommended_qty):
        frappe.throw("Recommendation changed; generate a fresh preview")
    policy=frappe.get_doc("Reorder Policy",h.policy)
    if automatic and (not policy.automatic_update_enabled or policy.approval_required or r["status"]!="Preview"):
        return False
    if creating:
        if automatic or not settings.allow_new_reorder_rows or not policy.allow_new_reorder_rows:
            frappe.throw("New reorder rows require manual approval and both creation switches")
        if getdate(h.calculation_date)!=business_date():
            frappe.throw("Generate a current-date preview before creating reorder rows")
        request_type=r.get("material_request_type")
        if policy.material_request_type not in ("Manufacture","Purchase") or request_type!=policy.material_request_type:
            frappe.throw("Explicit Material Request Type is required on the policy for new rows")
        if number(h.recommended_level or 0)<=0 or number(h.recommended_qty or 0)<=0:
            frappe.throw("New reorder values must be positive")
        frappe.db.sql("SELECT name FROM `tabItem` WHERE name=%s FOR UPDATE",h.item_code)
        item=frappe.get_doc("Item",h.item_code)
        if any(x.warehouse==h.warehouse for x in item.reorder_levels):
            frappe.throw("Reorder row already exists; generate a fresh preview")
        if request_type=="Manufacture" and not frappe.db.exists("BOM",{"item":item.name,"is_active":1,"is_default":1,"docstatus":1}):
            frappe.throw("An active submitted default BOM is required for Manufacture")
        if request_type=="Purchase" and not item.is_purchase_item:
            frappe.throw("Item is not eligible for purchase")
        row=item.append("reorder_levels",{"warehouse":h.warehouse,"material_request_type":request_type})
    else:
        item,row=locked_item(h)
        if row.material_request_type != r.get("material_request_type"):
            frappe.throw("Material Request Type changed; generate a fresh preview")
        if number(row.warehouse_reorder_level or 0)!=number(h.previous_level or 0) or number(row.warehouse_reorder_qty or 0)!=number(h.previous_qty or 0):
            frappe.throw("Existing reorder values changed; generate a fresh preview")
    row.warehouse_reorder_level=h.recommended_level
    row.warehouse_reorder_qty=h.recommended_qty
    # Preserve warehouse, warehouse group and request type.
    item.save()
    frappe.db.set_value(HISTORY,h.name,{"status":"Automatically Applied" if automatic else "Approved",
        "applied_by":frappe.session.user,"applied_at":now_datetime(),
        "reorder_row":row.name,"created_reorder_row":int(creating)})
    return True

@frappe.whitelist(methods=["POST"])
def apply(name):
    require_admin()
    return apply_one(name)

@frappe.whitelist(methods=["POST"])
def rollback(name):
    require_admin()
    h=locked_history(name)
    if h.status not in ("Approved","Automatically Applied"):
        frappe.throw("Only applied calculations can be reverted")
    item,row=locked_item(h)
    if number(row.warehouse_reorder_level or 0)!=number(h.recommended_level or 0) or number(row.warehouse_reorder_qty or 0)!=number(h.recommended_qty or 0):
        frappe.throw("Current values differ; manual review required")
    newer=frappe.db.exists(HISTORY,{"reorder_row":h.reorder_row,"applied_at":[">",h.applied_at],"status":["in",["Approved","Automatically Applied"]]})
    if newer: frappe.throw("A later application exists; manual review required")
    snapshot=frappe.parse_json(h.details or "{}")
    if snapshot.get("material_request_type") and row.material_request_type != snapshot["material_request_type"]:
        frappe.throw("Material Request Type changed; manual review required")
    if h.created_reorder_row:
        item.remove(row)
    else:
        row.warehouse_reorder_level=h.previous_level
        row.warehouse_reorder_qty=h.previous_qty
    item.save()
    frappe.db.set_value(HISTORY,h.name,{"status":"Reverted","reason":"Reverted by "+frappe.session.user+" at "+str(now_datetime())})
    return True
