"""Separate read-only replenishment monitor. It never creates Material Requests."""
from decimal import Decimal
import frappe
from qcmc_logic.dynamic_reorder_calculation import number
from qcmc_logic.dynamic_reorder_service import preview_rows


def assess(row, open_requests):
    result = dict(row,can_create_request=False,candidate_qty=Decimal(0),
                  open_material_requests=sorted({r["name"] for r in open_requests}))
    if row.get("status") not in ("Preview","Pending Approval") or any(row.get(k) is None for k in ("reorder_level","reorder_qty","projected_qty")):
        status = "Review Required"
    elif row.get("production_mode") != "Make to Stock":
        status = "Make to Order"
    elif row.get("legacy_reorder_rows"):
        status = "Legacy Reorder Conflict"
    elif open_requests:
        # Submitted demand already contributes to projected stock. Do not subtract
        # it a second time. Drafts are not in Bin and must also suppress duplicates.
        status = "Open Material Request"
    elif number(row["projected_qty"]) > number(row["reorder_level"]) or not (number(row["reorder_level"]) or number(row["reorder_qty"])):
        status = "Above Reorder Level"
    else:
        status = "Preview Candidate"
        result["candidate_qty"] = max(number(row["reorder_qty"]),number(row["reorder_level"])-number(row["projected_qty"]))
    result["monitor_status"] = status
    result["monitor_reason"] = "Preview only. Request creation requires validated ERPNext integration and transactional duplicate protection."
    return result


def approved_result(row, state, enabled):
    h, item, policy, request_type, projected, qty, requests = state
    result = dict(row, approval=h.name, reorder_level=h.recommended_level,
        reorder_qty=h.recommended_qty, projected_qty=projected,
        candidate_qty=Decimal(0), open_material_requests=requests,
        can_create_request=False, reason="")
    from qcmc_logic.dynamic_reorder_replenishment import manufacturing_readiness
    readiness, reason, bom = manufacturing_readiness(item.name,h.company,request_type)
    result.update(request_type=request_type,manufacturing_readiness=readiness,default_bom=bom)
    if requests:
        status, action = "Open Material Request", "Review existing requests before ordering more."
        if readiness == "BOM Required":
            action += " " + reason
    elif not qty:
        status, action = "Above Reorder Level", "No replenishment required."
    elif readiness not in ("Ready","Not Applicable"):
        status, action = readiness, reason
        result["candidate_qty"] = qty
    else:
        status = "Replenishment Required"
        action = ("Run Replenishment Now from your mapping." if enabled else
                  "Stock is low. Enable request generation in Reorder Settings before running replenishment.")
        result["candidate_qty"] = qty
        result["can_create_request"] = enabled
    return dict(result, monitor_status=status, monitor_reason=action)


def monitor_rows(company, mapping, item_code=None):
    from qcmc_logic.dynamic_reorder_replenishment import approved_state, manual_enabled
    from qcmc_logic.dynamic_reorder_service import load_mapping
    from qcmc_logic.dynamic_reorder_clock import business_date
    from qcmc_logic.dynamic_reorder_policy import active_on, mapping_warehouses, production_mode
    if frappe.session.user != "Administrator":
        frappe.throw("Administrator access required",frappe.PermissionError)
    config, policy = load_mapping(company,mapping,business_date())
    if not active_on(config,business_date()) or not policy.enabled:
        return []
    warehouses = mapping_warehouses(config)
    filters = dict(disabled=0,is_stock_item=1,has_variants=0,
        custom_inventory_group=policy.inventory_category,custom_inventory_type_=policy.inventory_type)
    if item_code:
        filters["name"] = item_code
    items = frappe.get_all("Item",filters=filters,fields=["name","item_name","stock_uom"],order_by="name")
    enabled = manual_enabled()
    output = []
    for offset in range(0,len(items),500):
        chunk = items[offset:offset+500]
        names = [i.name for i in chunk]
        stock = {}
        for b in frappe.get_all("Bin",filters={"item_code":["in",names],"warehouse":["in",warehouses]},
                fields=["item_code","projected_qty"]):
            stock[b.item_code] = stock.get(b.item_code,Decimal(0))+number(b.projected_qty or 0)
        owned = {}
        for r in frappe.get_all("Item Reorder",filters={"parent":["in",names],"parenttype":"Item",
                "parentfield":"reorder_levels","custom_reorder_mapping":mapping},
                fields=["parent","custom_reorder_history","custom_managed_reorder"]):
            owned.setdefault(r.parent,[]).append(r)
        for item in chunk:
            row = dict(item_code=item.name,item_name=item.item_name,stock_uom=item.stock_uom,
                company=company,mapping=mapping,warehouse=config.replenishment_warehouse,
                production_mode=production_mode(policy.inventory_category),
                projected_qty=stock.get(item.name,Decimal(0)),reorder_level=None,reorder_qty=None,
                candidate_qty=Decimal(0),open_material_requests=[],can_create_request=False,
                request_type=policy.material_request_type,manufacturing_readiness="Not Evaluated")
            records = owned.get(item.name,[])
            if row["production_mode"] != "Make to Stock":
                row.update(monitor_status="Make to Order",monitor_reason="Replenish against actual orders, not stock thresholds.")
            elif not records:
                row.update(monitor_status="Needs Approval",monitor_reason="Calculate recommendations and approve valid reorder values first.")
            elif len(records)!=1 or not records[0].custom_managed_reorder or not records[0].custom_reorder_history:
                row.update(monitor_status="Review Required",monitor_reason="Review managed Item Reorder ownership.")
            else:
                row["approval"] = records[0].custom_reorder_history
                try:
                    row = approved_result(row,approved_state(row["approval"],read_only=True),enabled)
                except frappe.ValidationError as exc:
                    frappe.clear_messages()
                    row.update(monitor_status="Review Required",monitor_reason=str(exc))
            output.append(row)
    order = {"BOM Required":0,"Replenishment Required":1,"Review Required":2,"Open Material Request":3,
             "Needs Approval":3,"Above Reorder Level":4,"Make to Order":5}
    return sorted(output,key=lambda r:(order.get(r["monitor_status"],99),r["item_code"]))


def execute(filters=None):
    f = frappe._dict(filters or {})
    columns = [dict(fieldname=name,label=label,fieldtype=kind,options=options,width=width) for name,label,kind,options,width in (
        ("item_code","Item","Link","Item",160),
        ("mapping","Reorder Policy Mapping","Link","Reorder Policy Mapping",180),
        ("warehouse","Replenishment Warehouse","Link","Warehouse",200),
        ("monitor_status","Monitoring Status","Data",None,210),
        ("production_mode","Production Mode","Data",None,140),
        ("request_type","Request Type","Data",None,130),
        ("manufacturing_readiness","Manufacturing Readiness","Data",None,190),
        ("default_bom","Default BOM","Link","BOM",180),
        ("projected_qty","Combined Projected Stock","Float",None,180),
        ("reorder_level","Approved ROL","Float",None,130),
        ("reorder_qty","Approved ROQ","Float",None,130),
        ("candidate_qty","Suggested Request Qty","Float",None,170),
        ("approval","Approved Calculation","Link","Reorder Calculation History",190),
        ("open_requests","Open Material Requests","Data",None,240),
        ("monitor_reason","Next Action / Review Reason","Data",None,400),
    )]
    if frappe.session.user != "Administrator":
        frappe.throw("Administrator access required",frappe.PermissionError)
    rows = monitor_rows(f.company,f.mapping,f.item_code) if f.company and f.mapping else []
    if f.monitor_status:
        rows = [r for r in rows if r["monitor_status"]==f.monitor_status]
    for row in rows:
        row["open_requests"] = ", ".join(row["open_material_requests"])
    return columns, rows
