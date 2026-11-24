"""Administrator-only Dynamic Reorder analysis report."""
import frappe
from qcmc_logic.dynamic_reorder_service import preview_rows
from qcmc_logic.dynamic_reorder_health import classify, HEALTH

def execute(filters=None):
    if frappe.session.user!="Administrator":
        frappe.throw("Administrator access required",frappe.PermissionError)
    f=frappe._dict(filters or {})
    columns=[]
    for field,label,kind,options,width in [
        ("item_code","Item","Link","Item",150),("item_name","Item Name","Data",None,200),
        ("inventory_health","Inventory Health","Data",None,160),("health_reason","Health Remarks","Data",None,300),
        ("status","Status","Data",None,190),("reason","Remarks","Data",None,340),
        ("warehouse","Warehouse","Link","Warehouse",180),("stock_uom","Stock UOM","Data",None,90),
        ("policy_name","Policy Name","Data",None,220),("policy","Policy Reference","Link","Reorder Policy",125),("demand_period_method","Demand Period","Data",None,190),("historical_start","From Date","Date",None,115),("historical_end","To Date","Date",None,115),("historical_days","Days","Int",None,75),("month_1","Segment 1 Demand","Float",None,120),
        ("month_2","Segment 2 Demand","Float",None,120),("month_3","Segment 3 Demand","Float",None,120),
        ("demand_breakdown","Period Demand Breakdown","Data",None,360),("gross_demand","Gross Demand","Float",None,120),("sales_returns","Returns","Float",None,100),
        ("net_demand","Net Demand","Float",None,120),("average_monthly","Average Monthly","Float",None,120),
        ("average_daily","Daily Demand","Float",None,120),("forecast_daily","Forecast Daily","Float",None,120),
        ("lead_time","Lead Time","Int",None,90),("safety_days","Safety Days","Int",None,90),
        ("safety_stock","Safety Stock","Float",None,110),("coverage_days","Coverage Days","Int",None,110),
        ("actual_qty","Actual Stock","Float",None,110),("projected_qty","Projected Stock","Float",None,120),
        ("previous_level","Previous ROL","Float",None,115),("reorder_level","Recommended ROL","Float",None,145),
        ("level_change_pct","ROL Change %","Percent",None,115),("previous_qty","Previous ROQ","Float",None,115),
        ("reorder_qty","Recommended ROQ","Float",None,145),("qty_change_pct","ROQ Change %","Percent",None,115),
        ("suggested_replenishment","Suggested Request","Float",None,145),
        ("stock_coverage_days","Actual Coverage Days","Float",None,135),("projected_coverage_days","Projected Coverage Days","Float",None,150),("overstock_coverage_days","Overstock Limit Days","Int",None,145),("maximum_stock","Maximum Stock","Float",None,130),("material_request_type","Request Type","Data",None,130),
        ]:
        columns.append(dict(fieldname=field,label=label,fieldtype=kind,options=options,width=width))
    if not f.company or not f.warehouse:
        return columns,[]
    rows=preview_rows(f.company,f.warehouse,f.item_group,f.item_code,f.as_of,f.period_method or None,f.rolling_days if f.period_method=="Rolling Days" else None)
    if f.status: rows=[r for r in rows if r["status"]==f.status]
    if f.policy: rows=[r for r in rows if r.get("policy")==f.policy]
    if f.seasonal_only: rows=[r for r in rows if r.get("seasonal_indices")]
    if f.changed_only: rows=[r for r in rows if "reorder_level" in r and (r["reorder_level"]!=r.get("previous_level") or r["reorder_qty"]!=r.get("previous_qty"))]
    for r in rows:
        monthly=list((r.get("monthly_demand") or {}).values())
        for i in range(3): r["month_"+str(i+1)]=monthly[i] if i<len(monthly) else None
        r["demand_breakdown"] = "; ".join(f"{a} to {b}: {q}" for (a,b),q in zip(r.get("period_segments") or [],monthly))
        r["historical_days"] = sum((frappe.utils.getdate(b)-frappe.utils.getdate(a)).days+1 for a,b in r.get("period_segments") or [])
        r["average_monthly"]=r.get("net_demand",0)/len(monthly) if monthly and r.get("net_demand") is not None and r.get("demand_period_method")=="Complete Calendar Months" else None
        r["stock_coverage_days"]=float(r.get("actual_qty") or 0)/float(r["forecast_daily"]) if r.get("forecast_daily") else None
    for r in rows:
        r["inventory_health"], r["health_reason"] = classify(r)
        policy = r.get("policy_snapshot") or {}
        r["policy_name"] = policy.get("policy_name") or r.get("policy")
        r["overstock_coverage_days"] = policy.get("overstock_coverage_days") if policy.get("overstock_coverage_days") is not None else 90
        r["maximum_stock"] = policy.get("maximum_stock")
        r["projected_coverage_days"] = float(r["projected_qty"])/float(r["forecast_daily"]) if r.get("forecast_daily") and r.get("projected_qty") is not None else None
    if f.inventory_health:
        rows=[r for r in rows if r["inventory_health"]==f.inventory_health]
    summary=[dict(label=h,value=sum(r["inventory_health"]==h for r in rows),datatype="Int",indicator={"Critical Stock":"Red","Reorder Required":"Orange","Healthy Stock":"Green","Overstock":"Orange","No Demand":"Grey","Not Evaluated":"Grey"}[h]) for h in HEALTH]
    for label,value in [("Items Analyzed",len(rows)),("Higher ROL",sum((r.get("level_change_pct") or 0)>0 for r in rows)),
        ("Lower ROL",sum((r.get("level_change_pct") or 0)<0 for r in rows)),
        ("Requires Review",sum(r["status"] in ("Pending Approval","New Reorder Configuration") for r in rows)),
        ("Skipped",sum(r["status"]=="Skipped" for r in rows)),("Failed",sum(r["status"]=="Failed" for r in rows))]:
        summary.append(dict(label=label,value=value,datatype="Int"))
    return columns,rows,None,None,summary
