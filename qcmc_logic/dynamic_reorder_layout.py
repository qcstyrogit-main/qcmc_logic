"""Idempotent metadata upgrade; preserve existing documents and Link references."""
import frappe

LAYOUTS = {
 "Reorder Execution History": [("Execution",["scheduled_date","status","attempts"],["catch_up","started_at","finished_at"]),("Details",["last_error","details"])],
 "Reorder Settings": [("Operating Controls",["enabled","preview_only"],["automatic_update_enabled","allow_new_reorder_rows","first_scheduled_date"]),("Notifications",["email_execution_alerts"])],
 "Seasonal Demand Profile": [("Profile",["profile_name","mode"],["history_months"]),("Monthly Factors",["month_1","month_2","month_3","month_4"],["month_5","month_6","month_7","month_8"],["month_9","month_10","month_11","month_12"])],
 "Reorder Policy": [("Policy",["policy_name","inventory_category"],["inventory_type","enabled"]),("Demand and Replenishment",["demand_period_method","historical_months","rolling_days","lead_time","safety_days"],["coverage_days","seasonal_profile","deduct_returns"]),("Quantity Limits",["minimum_stock","maximum_stock","overstock_coverage_days","moq"],["order_multiple","production_batch","material_request_type"]),("Update Controls",["preserve_no_demand","increase_limit","decrease_limit"],["automatic_update_enabled","approval_required","allow_new_reorder_rows"]),("Notes",["remarks"])],
 "Reorder Policy Mapping": [("Policy and Scope",["policy","company","enabled"],["item_code","item_group","include_item_descendants"],["warehouse","include_warehouse_descendants"]),("Priority and Validity",["priority","effective_from"],["effective_to"])],
 "Item Reorder Override": [("Item and Policy",["company","item_code","warehouse"],["policy","enabled","exclude_item"]),("Production",["production_mode","allow_make_to_order"],["effective_from","effective_to"]),("Calculation Overrides",["override_parameters","historical_months","lead_time","safety_days","coverage_days"],["minimum_stock","maximum_stock","moq","order_multiple","production_batch"]),("Seasonal and Fixed Values",["override_seasonal_profile","seasonal_profile"],["fixed_reorder_values","fixed_reorder_level","fixed_reorder_qty"]),("Reason",["reason"])],
 "Reorder Calculation History": [("Result",["item_code","company","warehouse","policy"],["status","calculation_date","batch","calculation_key"]),("Reorder Comparison",["previous_level","recommended_level","actual_qty"],["previous_qty","recommended_qty","projected_qty"]),("Audit",["reorder_row","created_reorder_row","applied_by","applied_at"],["reason"]),("Calculation Details",["details"])]
}

def rename_existing(names):
    for name in names:
        if frappe.db.exists("DocType", "QCMC " + name) and frappe.db.exists("DocType", name):
            frappe.throw("DocType naming conflict: " + name)
    for name in names:
        old = "QCMC " + name
        if frappe.db.exists("DocType", old):
            if frappe.db.exists("DocType", name):
                frappe.throw("DocType naming conflict: " + name)
            frappe.rename_doc("DocType", old, name, force=True)
            frappe.clear_cache(doctype=old)
            frappe.clear_cache(doctype=name)

def layout(name, fields):
    doc = frappe.get_doc("DocType", name)
    existing = {f.fieldname:f for f in doc.fields}
    for definition in fields:
        if definition["fieldname"] not in existing:
            f=doc.append("fields", definition)
            existing[f.fieldname]=f
    ordered=[]
    for i, (label,*columns) in enumerate(LAYOUTS[name]):
        for j, column in enumerate(columns):
            key="dr_section_"+str(i) if j==0 else "dr_column_"+str(i)+"_"+str(j)
            f=existing.get(key)
            if not f:
                f=doc.append("fields",{"fieldname":key,"fieldtype":"Section Break" if j==0 else "Column Break","label":label if j==0 else ""})
            if j==0 and label in ("Calculation Overrides","Seasonal and Fixed Values","Calculation Details"):
                f.collapsible=1
            ordered.append(f)
            ordered.extend(existing[k] for k in column if k in existing)
    used={f.fieldname for f in ordered}
    ordered.extend(f for f in doc.fields if f.fieldname not in used)
    if name=="Reorder Settings":
        existing["first_scheduled_date"].read_only=1
    if name=="Reorder Policy":
        existing["rolling_days"].depends_on="eval:doc.demand_period_method=='Rolling Days'"
        existing["historical_months"].depends_on="eval:doc.demand_period_method!='Rolling Days'"
    if name=="Item Reorder Override":
        for f in ordered:
            if f.fieldname in ("historical_months","lead_time","safety_days","coverage_days","minimum_stock","maximum_stock","moq","order_multiple","production_batch"):
                f.depends_on="eval:doc.override_parameters"
            elif f.fieldname=="seasonal_profile":
                f.depends_on="eval:doc.override_seasonal_profile"
            elif f.fieldname in ("fixed_reorder_level","fixed_reorder_qty"):
                f.depends_on="eval:doc.fixed_reorder_values"
    if name=="Seasonal Demand Profile":
        for f in ordered:
            if f.fieldname.startswith("month_"):
                f.label=("January February March April May June July August September October November December".split())[int(f.fieldname[6:])-1]
                f.depends_on="eval:doc.mode=='Manual'"
    if name in ("Reorder Calculation History","Reorder Execution History"):
        for f in ordered:
            if f.fieldtype not in ("Section Break","Column Break"):
                f.read_only=1
    doc.set("fields",ordered)
    for idx, field in enumerate(doc.fields, 1):
        field.idx = idx
    doc.save()
    frappe.clear_cache(doctype=name)
