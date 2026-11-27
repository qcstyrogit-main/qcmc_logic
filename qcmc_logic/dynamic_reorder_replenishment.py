"""Approved consolidated replenishment with manual draft creation.
Scheduled draft entry point is opt-in; no submission or stock movements.
"""
import frappe
from frappe.utils import add_days, cint, getdate
from decimal import Decimal, ROUND_CEILING
from qcmc_logic.dynamic_reorder_calculation import number
from qcmc_logic.dynamic_reorder_clock import business_date
from qcmc_logic.dynamic_reorder_policy import active_on, mapping_warehouses
from qcmc_logic.dynamic_reorder_service import load_mapping, require_admin


def candidate_quantity(level, qty, projected, precision=0):
    level, qty, projected = map(number, (level, qty, projected))
    if level < 0 or qty < 0:
        raise ValueError("Negative reorder configuration")
    if not (level or qty) or projected > level:
        return Decimal(0)
    return max(qty, level-projected).quantize(Decimal(1).scaleb(-precision), rounding=ROUND_CEILING)


def manufacturing_readiness(item_code, company, request_type):
    """Mirror native default BOM selection; reject inactive or wrong-company BOMs."""
    if request_type == "Purchase":
        return "Not Applicable", "", None
    if request_type != "Manufacture":
        return "Review Required", "Material Request Type requires review", None
    selected = frappe.db.get_value("BOM", {"item":item_code,"is_default":1,"docstatus":1},
        ["name","company","is_active"],as_dict=True)
    if not selected:
        variant = frappe.db.get_value("Item",item_code,"variant_of")
        if variant:
            selected = frappe.db.get_value("BOM",{"item":variant,"is_default":1},
                ["name","company","is_active","docstatus"],as_dict=True)
            if selected and selected.docstatus != 1:
                selected = None
    if not selected:
        return "BOM Required", "Create and submit an active default BOM for "+item_code, None
    if not selected.is_active or selected.company != company:
        return "BOM Required", "Default BOM must be active and belong to "+company, None
    return "Ready", "", selected.name


def approved_state(name, automatic=False, read_only=False):
    # Read-only assessment must never become an authorization bypass.
    if read_only and frappe.session.user != "Administrator":
        frappe.throw("Administrator access required", frappe.PermissionError)
    h = frappe.get_doc("Reorder Calculation History", name, for_update=not read_only)
    if h.status != "Approved" or not h.mapping:
        frappe.throw("An approved consolidated calculation is required")
    settings = frappe.get_single("Reorder Settings")
    if not read_only:
        if not settings.enabled or settings.preview_only or settings.automatic_update_enabled:
            frappe.throw("Manual replenishment requires enabled Reorder Settings and automatic update disabled")
        mode = settings.get("replenishment_mode") or "Disabled"
        if mode not in ("Manual Draft","Automatic Draft") or (automatic and mode!="Automatic Draft"):
            frappe.throw("Draft replenishment is disabled in Reorder Settings")
        if cint(frappe.db.get_single_value("Stock Settings", "auto_indent")):
            frappe.throw("Native auto reorder must remain disabled until integration is validated")
    today = business_date()
    if not read_only:
        frappe.db.sql("SELECT name FROM `tabCompany` WHERE name=%s FOR UPDATE", h.company)
        frappe.db.sql("SELECT name FROM `tabItem` WHERE name=%s FOR UPDATE", h.item_code)
    mapping, policy = load_mapping(h.company, h.mapping, today)
    policy = frappe.get_doc("Reorder Policy", policy.name, for_update=not read_only)
    if automatic and not mapping.get("automatic_draft_replenishment"):
        frappe.throw("Automatic draft replenishment is disabled for this mapping")
    if not active_on(mapping, today) or not policy.enabled or policy.inventory_category != "FG":
        frappe.throw("Active Make to Stock mapping and policy required")
    warehouses = sorted(mapping_warehouses(mapping))
    snap = frappe.parse_json(h.details or "{}")
    if snap.get("schema_version") != 2 or snap.get("production_mode") != "Make to Stock" or sorted(snap.get("warehouses") or []) != warehouses or mapping.replenishment_warehouse != h.warehouse:
        frappe.throw("Mapping scope changed; approve a fresh configuration")
    # Conservative first release: overrides must be reviewed separately.
    if snap.get("override") or frappe.db.exists("Item Reorder Override", {"mapping":h.mapping,"item_code":h.item_code,"enabled":1}):
        frappe.throw("Item override requires replenishment review")
    if h.policy != policy.name:
        frappe.throw("Policy changed; approve a fresh configuration")
    saved_policy = snap.get("policy_snapshot") or {}
    for field in ("lead_time","safety_days","coverage_days","minimum_stock","maximum_stock",
                  "moq","order_multiple","production_batch","material_request_type",
                  "demand_period_method","rolling_days","historical_months","seasonal_profile",
                  "demand_delivery","demand_manufacture","demand_intercompany","demand_provincial","deduct_returns"):
        if str(saved_policy.get(field)) != str(policy.get(field)):
            frappe.throw("Policy parameters changed; approve a fresh configuration")
    item = frappe.get_doc("Item", h.item_code, for_update=not read_only)
    if item.disabled or not item.is_stock_item or item.has_variants or (item.end_of_life and str(item.end_of_life)!="0000-00-00" and getdate(item.end_of_life)<=today):
        frappe.throw("Item is not eligible for replenishment")
    if (item.custom_inventory_group,item.custom_inventory_type_) != (policy.inventory_category,policy.inventory_type):
        frappe.throw("Item classification changed")
    rows = [r for r in item.reorder_levels if r.get("custom_reorder_mapping")==h.mapping]
    if len(rows)!=1:
        frappe.throw("Exactly one managed reorder row required")
    row = rows[0]
    if not row.custom_managed_reorder or row.name!=h.reorder_row or row.custom_reorder_history!=h.name or row.warehouse!=h.warehouse or row.warehouse_group not in (None,"",h.warehouse):
        frappe.throw("Managed reorder ownership changed")
    if any(r.name!=row.name and (r.warehouse in warehouses or r.warehouse_group) for r in item.reorder_levels):
        frappe.throw("Conflicting reorder rows require review")
    if number(row.warehouse_reorder_level)!=number(h.recommended_level) or number(row.warehouse_reorder_qty)!=number(h.recommended_qty):
        frappe.throw("Approved reorder values changed")
    request_type = row.material_request_type
    if request_type not in ("Manufacture","Purchase") or policy.material_request_type not in ("Preserve",request_type) or snap.get("applied_request_type",request_type)!=request_type:
        frappe.throw("Material Request Type requires review")
    # Current locking reads, not stale prepared-report values.
    bins = frappe.db.sql("""SELECT projected_qty FROM `tabBin`
        WHERE item_code=%s AND warehouse IN %s""" + ("" if read_only else " FOR UPDATE"),
        (item.name,tuple(warehouses)),as_dict=True)
    projected = sum((number(b.projected_qty or 0) for b in bins),Decimal(0))
    # Conservatively block ordered requests too: downstream supply may still be open.
    requests = frappe.db.sql("""SELECT mr.name FROM `tabMaterial Request` mr
        JOIN `tabMaterial Request Item` mri ON mri.parent=mr.name
        WHERE mr.company=%s AND mr.docstatus IN (0,1)
        AND COALESCE(mr.status,'Draft') NOT IN ('Stopped','Cancelled','Received','Issued','Transferred','Manufactured')
        AND mri.item_code=%s AND mri.warehouse IN %s""" + ("" if read_only else " FOR UPDATE"),
        (h.company,item.name,tuple(warehouses)),as_dict=True)
    precision = 0 if frappe.db.get_value("UOM",item.stock_uom,"must_be_whole_number") else cint(frappe.db.get_default("float_precision") or 3)
    qty = candidate_quantity(row.warehouse_reorder_level,row.warehouse_reorder_qty,projected,precision)
    maximum = number(policy.maximum_stock or 0)
    if qty and maximum and projected+qty>maximum:
        frappe.throw("Replenishment would exceed maximum stock; manual review required")
    return h,item,policy,request_type,projected,qty,sorted({r.name for r in requests})


@frappe.whitelist(methods=["POST"])
def create_draft(name):
    require_admin()
    return _create_draft(name)


def _create_draft(name, automatic=False):
    h,item,policy,request_type,projected,qty,requests = approved_state(name,automatic=automatic)
    if requests:
        return {"status":"Open Material Request","requests":requests}
    if not qty:
        return {"status":"Above Reorder Level","projected_qty":float(projected)}
    readiness, reason, bom = manufacturing_readiness(item.name,h.company,request_type)
    if readiness not in ("Ready","Not Applicable"):
        return {"status":readiness,"reason":reason,"item_code":item.name}
    today = business_date()
    due = add_days(today,max(0,cint(policy.lead_time)))
    meta = frappe.get_meta("Material Request")
    if not all(meta.has_field(f) for f in ("custom_replenishment_mapping","custom_replenishment_history")):
        frappe.throw("Replenishment metadata is not installed")
    mr = frappe.new_doc("Material Request")
    mr.update(dict(company=h.company, material_request_type=request_type,
                   transaction_date=today,schedule_date=due,set_warehouse=h.warehouse,auto_created_via_reorder=0,
                   custom_replenishment_mapping=h.mapping,custom_replenishment_history=h.name))
    mr.append("items",dict(item_code=item.name,item_name=item.item_name,
        description=item.description or item.item_name,warehouse=h.warehouse,
        schedule_date=due,qty=float(qty),uom=item.stock_uom,stock_uom=item.stock_uom,
        conversion_factor=1))
    mr.insert()
    mr.add_comment("Comment","Consolidated replenishment from approved calculation " + h.name)
    h.add_comment("Comment","Draft Material Request " + mr.name + " created for " + str(qty) + " " + item.stock_uom)
    return {"status":"Draft Created","name":mr.name,"qty":float(qty),"warehouse":h.warehouse}


def automatic_enabled():
    settings = frappe.get_single("Reorder Settings")
    return bool(settings.get("replenishment_mode")=="Automatic Draft" and settings.enabled
                and not settings.preview_only and not settings.automatic_update_enabled
                and not cint(frappe.db.get_single_value("Stock Settings","auto_indent")))


def manual_enabled():
    settings = frappe.get_single("Reorder Settings")
    return bool(settings.get("replenishment_mode") in ("Manual Draft","Automatic Draft")
                and settings.enabled and not settings.preview_only
                and not settings.automatic_update_enabled
                and not cint(frappe.db.get_single_value("Stock Settings","auto_indent")))


@frappe.whitelist(methods=["POST"])
def run_now(mapping=None):
    require_admin()
    return _run_batch(automatic=False, mapping=mapping or None)


def scheduled_drafts():
    return _run_batch(automatic=True)


def _run_batch(automatic=True, mapping=None):
    """Shared execution lock, eligibility checks and per-item transaction logging."""
    from frappe.utils import now_datetime
    if not frappe.db.exists("DocType","Replenishment Execution History"):
        return {"status":"Not Installed"}
    if frappe.session.user != "Administrator":
        frappe.throw("Administrator access required", frappe.PermissionError)
    enabled = automatic_enabled if automatic else manual_enabled
    if not enabled():
        return {"status":"Disabled"}
    if mapping and not frappe.db.exists("Reorder Policy Mapping", {"name":mapping,"enabled":1}):
        frappe.throw("Select an enabled Reorder Policy Mapping")
    lock = frappe.cache.lock("qcmc_consolidated_replenishment", timeout=7200)
    if not lock.acquire(blocking=False):
        return {"status":"Already Running"}
    counts = {"checked":0,"created":0,"skipped":0,"failed":0}
    run = None
    details = []
    try:
        run = frappe.get_doc(dict(doctype="Replenishment Execution History",
            started_at=now_datetime(),status="Running",trigger_type="Scheduled" if automatic else "Manual",
            triggered_by=frappe.session.user,mapping=mapping,**counts)).insert(ignore_permissions=True)
        frappe.db.commit()
        # Only approved, currently-owned rows in individually enabled mappings.
        sql = """SELECT h.name FROM `tabReorder Calculation History` h
            JOIN `tabItem Reorder` r ON r.name=h.reorder_row AND r.custom_reorder_history=h.name
            JOIN `tabReorder Policy Mapping` m ON m.name=h.mapping
            WHERE h.status='Approved' AND r.custom_managed_reorder=1 AND m.enabled=1"""
        if automatic:
            sql += " AND m.automatic_draft_replenishment=1"
        params = ()
        if mapping:
            sql += " AND m.name=%s"
            params = (mapping,)
        names = frappe.db.sql(sql+" ORDER BY h.name",params,pluck=True)
        stopped = False
        for name in names:
            if not enabled():
                stopped = True
                break
            counts["checked"] += 1
            try:
                result = _create_draft(name, automatic=automatic)
            except frappe.ValidationError as exc:
                frappe.db.rollback()
                frappe.clear_messages()
                result = {"status":"Review Required","reason":str(exc)}
            except Exception:
                frappe.db.rollback()
                result = {"status":"Failed","reason":"Review Error Log"}
                frappe.log_error(title="Consolidated replenishment failed: "+name)
            bucket = ("created" if result["status"]=="Draft Created" else
                      "failed" if result["status"]=="Failed" else "skipped")
            counts[bucket] += 1
            details.append(dict(calculation=name,**result))
            frappe.db.set_value("Replenishment Execution History",run.name,
                dict(**counts,details=frappe.as_json(details)))
            frappe.db.commit()
        status = "Stopped" if stopped else ("Completed with Errors" if counts["failed"] else "Completed")
        frappe.db.set_value("Replenishment Execution History",run.name,
            dict(**counts,status=status,finished_at=now_datetime(),details=frappe.as_json(details)))
        frappe.db.commit()
        return dict(**counts,status=status,execution=run.name)
    except Exception:
        frappe.db.rollback()
        if run:
            frappe.db.set_value("Replenishment Execution History",run.name,
                dict(status="Failed",finished_at=now_datetime(),last_error="Review Error Log"))
        frappe.log_error(title="Consolidated replenishment execution failed")
        frappe.db.commit()
        raise
    finally:
        lock.release()
