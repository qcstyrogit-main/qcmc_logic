"""Idempotent metadata upgrade; preserve existing documents and Link references."""
import frappe

LAYOUTS = {
 "Reorder Calculation Batch": [("Calculation",["display_title","company","mapping","warehouse"],["status","calculation_date","trigger_type","calculated_by"]),("Summary",["total_items","pending_items","approved_items","reverted_items"],["unchanged_items","review_items","failed_items"]),("Calculated Items",["results_table"]),("Details",["parameters","last_error"])],
 "Reorder Calculation Item": [("Result",["batch","item_code","status"],["approval_history","projected_qty"]),("Comparison",["previous_level","recommended_level"],["previous_qty","recommended_qty"]),("Details",["reason","snapshot"])],
 "Reorder Schedule Settings": [("Scheduling Configuration",["enabled","frequency","execution_weekday","day_of_month"],["execution_time","effective_from"]),("Execution Recovery",["recover_missed_executions","maximum_retry_attempts"]),("Schedule Summary",["schedule_overview"])],
 "Replenishment Execution History": [("Trigger",["trigger_type","triggered_by"],["mapping"]),("Execution",["started_at","status","checked","created"],["finished_at","skipped","failed"]),("Details",["details","last_error"])],
 "Reorder Execution History": [("Execution",["scheduled_date","status","attempts"],["catch_up","started_at","finished_at"]),("Details",["last_error","details"])],
 "Reorder Settings": [("Operating Controls",["enabled","preview_only"],["automatic_update_enabled","allow_new_reorder_rows","first_scheduled_date"]),("Notifications",["email_execution_alerts"]),("Replenishment",["replenishment_mode"]),("Overview and Getting Started",["operational_overview"])],
 "Seasonal Demand Profile": [("Profile",["profile_name","mode"],["history_months"]),("Monthly Factors",["month_1","month_2","month_3","month_4"],["month_5","month_6","month_7","month_8"],["month_9","month_10","month_11","month_12"])],
 "Reorder Policy": [("Policy",["policy_name","inventory_category"],["inventory_type","enabled"]),("Demand and Replenishment",["demand_period_method","historical_months","rolling_days","lead_time","safety_days"],["coverage_days","seasonal_profile","deduct_returns"]),("Demand Sources",["demand_delivery","demand_manufacture"],["demand_intercompany","demand_provincial"]),("Quantity Limits",["minimum_stock","maximum_stock","overstock_coverage_days","moq"],["order_multiple","production_batch","material_request_type"]),("Update Controls",["preserve_no_demand","increase_limit","decrease_limit"],["automatic_update_enabled","approval_required","allow_new_reorder_rows"]),("Notes",["remarks"])],
 "Reorder Policy Mapping": [("Policy and Scope",["mapping_name","policy","company"],["enabled","inventory_group","inventory_type"]),("Warehouses",["warehouses"],["replenishment_warehouse"]),("Validity",["effective_from"],["effective_to"]),("Migration Review",["migration_review_required","migration_note"],["legacy_scope_reviewed"]),("Replenishment",["transfer_source_warehouse","automatic_draft_replenishment"])],
 "Item Reorder Override": [("Item and Policy",["company","item_code","mapping"],["policy","enabled","exclude_item"]),("Validity",["effective_from","effective_to"]),("Calculation Overrides",["override_parameters","historical_months","lead_time","safety_days","coverage_days"],["minimum_stock","maximum_stock","moq","order_multiple","production_batch"]),("Seasonal and Fixed Values",["override_seasonal_profile","seasonal_profile"],["fixed_reorder_values","fixed_reorder_level","fixed_reorder_qty"]),("Reason",["reason","legacy_scope_reviewed"])],
 "Reorder Calculation History": [("Result",["item_code","company","mapping","warehouse","policy"],["status","calculation_date","batch","calculation_key"]),("Reorder Comparison",["previous_level","recommended_level","actual_qty"],["previous_qty","recommended_qty","projected_qty"]),("Audit",["reorder_row","created_reorder_row","applied_by","applied_at"],["reason"]),("Calculation Details",["details"])]
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
            if j==0:
                f.label=label
                f.collapsible=int(label in ("Calculation Overrides","Seasonal and Fixed Values","Calculation Details","Audit","Migration Review","Quantity Limits","Update Controls","Execution Recovery","Details"))
            ordered.append(f)
            ordered.extend(existing[k] for k in column if k in existing)
    used={f.fieldname for f in ordered}
    ordered.extend(f for f in doc.fields if f.fieldname not in used)
    if name=="Reorder Settings":
        existing["first_scheduled_date"].read_only=1
        existing["first_scheduled_date"].hidden=1
        existing["automatic_update_enabled"].read_only=1
        existing["automatic_update_enabled"].hidden=1
        existing["allow_new_reorder_rows"].read_only=0
        existing["allow_new_reorder_rows"].hidden=0
        existing["preview_only"].read_only=0
        existing["preview_only"].description="When enabled, only previews may be saved. Scheduled calculation remains preview-only."
        existing["replenishment_mode"].options="Disabled\nManual Draft\nAutomatic Draft"
        existing["replenishment_mode"].description="Disabled by default. Manual Draft permits an explicit request from an approved calculation. Automatic Draft checks enabled mappings every 15 minutes and creates drafts only."
    if name=="Reorder Schedule Settings":
        existing["effective_from"].read_only=1
        existing["execution_weekday"].depends_on="eval:doc.frequency=='Weekly'"
        existing["day_of_month"].depends_on="eval:doc.frequency=='Monthly'"
        existing["execution_time"].description="Philippine time (Asia/Manila). Checker runs every 15 minutes."
        existing["maximum_retry_attempts"].description="Total attempts per scheduled date, including the initial attempt (1–10)."
    if name=="Reorder Policy":
        category=existing["inventory_category"]
        # Preserve the stored fieldname and all policy references.
        if category.fieldtype != "Link" or category.options != "Inventory Group":
            if not frappe.db.exists("Inventory Group","FG"):
                frappe.throw("Inventory Group FG is required for reorder policy migration.")
            policies=frappe.get_all(name,fields=["name","inventory_category"])
            for policy in policies:
                value="FG" if policy.inventory_category=="Finished Goods" else policy.inventory_category
                if not value or not frappe.db.exists("Inventory Group",value):
                    frappe.throw("Review inventory group for reorder policy "+policy.name+": "+str(policy.inventory_category))
            for policy in policies:
                if policy.inventory_category=="Finished Goods":
                    frappe.db.set_value(name,policy.name,"inventory_category","FG",update_modified=False)
        category.fieldtype="Link"
        category.options="Inventory Group"
        category.default="FG"
        category.label="Inventory Group"
        existing["rolling_days"].depends_on="eval:doc.demand_period_method=='Rolling Days'"
        existing["historical_months"].depends_on="eval:doc.demand_period_method!='Rolling Days'"
    if name=="Reorder Policy Mapping":
        for k in ("item_code","item_group","include_item_descendants","warehouse","include_warehouse_descendants","priority"):
            existing[k].hidden=1
            existing[k].reqd=0
        for k in ("inventory_group","inventory_type","migration_review_required","migration_note"):
            existing[k].read_only=1
        existing["legacy_scope_reviewed"].description="Explicitly acknowledge replacing the preserved legacy item and warehouse scope with this V2 mapping scope."
        existing["mapping_name"].reqd=1
        existing["warehouses"].reqd=1
        existing["replenishment_warehouse"].reqd=1
        existing["automatic_draft_replenishment"].read_only=0
        existing["automatic_draft_replenishment"].description="Allow scheduled draft requests for this mapping only when global Automatic Draft mode is enabled."
    if name=="Item Reorder Override":
        for k in ("warehouse","production_mode","allow_make_to_order"):
            existing[k].hidden=1
            existing[k].reqd=0
        existing["mapping"].reqd=1
        existing["exclude_item"].default="0"
        existing["legacy_scope_reviewed"].description="Acknowledge that this override replaces its legacy warehouse scope and applies to every warehouse in the mapping."
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
    if name in ("Reorder Calculation Batch","Reorder Calculation Item","Reorder Calculation History","Reorder Execution History","Replenishment Execution History"):
        for f in ordered:
            if f.fieldtype not in ("Section Break","Column Break"):
                f.read_only=1
    if name=="Reorder Execution History":
        existing["scheduled_date"].unique=0
        existing["execution_key"].unique=1
        existing["execution_key"].hidden=1
        for perm in doc.permissions:
            perm.write=0
            perm.create=0
    # Presentation only: preserve database fieldnames, values and options.
    guidance = {
        "Reorder Settings": {
            "preview_only": ("Simulation Only (No Applying or Requests)", "Check this to prevent applying recommendations or generating replenishment requests."),
            "allow_new_reorder_rows": ("Allow New Item Reorder Rows", "Permit approval to create a new managed reorder row when one does not exist."),
            "replenishment_mode": ("Material Request Generation Mode", "Disabled: no requests. Manual Draft: run on demand. Automatic Draft: check enabled mappings every 15 minutes. Requests are never submitted automatically."),
        },
        "Reorder Schedule Settings": {
            "enabled": ("Enable Scheduled Calculations", "Schedules recommendations only, not Material Requests."),
            "frequency": ("Calculation Frequency", "How often to calculate new recommended reorder levels and quantities."),
        },
        "Reorder Policy": {
            "lead_time": ("Replenishment Lead Time (Days)", "Expected days from requesting supply until it is available. Example: 7."),
            "safety_days": ("Safety Stock Coverage (Days)", "Extra demand coverage for unexpected delays or demand. Example: 5."),
            "coverage_days": ("Order Quantity Coverage (Days)", "Target number of demand days covered by a replenishment order. Example: 15."),
            "moq": ("Minimum Order Quantity", "Smallest permitted replenishment order; zero means no minimum."),
            "maximum_stock": ("Maximum Stock Limit", "Zero means no configured maximum; exceeding a positive limit requires review."),
            "material_request_type": ("Replenishment Request Type", "Manufacture for production; Purchase for purchasing; Preserve keeps the existing type."),
        },
        "Reorder Policy Mapping": {
            "warehouses": ("Warehouses to Combine", "Demand and stock are combined across these warehouses."),
            "replenishment_warehouse": ("Replenishment Destination", "The warehouse that will receive the requested supply. Must be in the combined list."),
            "transfer_source_warehouse": ("Transfer Source Warehouse", "Required for provincial Transfer configurations. Select an eligible non-provincial FG serving warehouse of the same company."),
            "automatic_draft_replenishment": ("Enable Automatic Draft Requests", "Requires global Automatic Draft mode. Manual execution remains available in permitted modes."),
        },
        "Reorder Calculation History": {
            "recommended_level": ("Recommended Reorder Level (ROL)", "Proposed stock threshold for replenishment."),
            "recommended_qty": ("Recommended Reorder Quantity (ROQ)", "Proposed replenishment quantity."),
            "actual_qty": ("Combined Actual Stock at Calculation", "Historical snapshot saved with this calculation, not current stock."),
            "projected_qty": ("Combined Projected Stock at Calculation", "Saved projected stock snapshot, not current stock."),
            "reorder_row": ("Item Reorder Reference", "Internal reference to the applied Item Master row."),
        },
    }
    for fieldname,(label,description) in guidance.get(name,{}).items():
        if fieldname in existing:
            existing[fieldname].label=label
            existing[fieldname].description=description
    list_columns = {
        "Reorder Calculation Batch": ("calculation_date","mapping","status","total_items","pending_items"),
        "Reorder Calculation Item": ("batch","item_code","status"),
        "Reorder Policy": ("policy_name","inventory_category","inventory_type","enabled"),
        "Reorder Policy Mapping": ("mapping_name","company","replenishment_warehouse","enabled"),
        "Item Reorder Override": ("item_code","mapping","enabled","exclude_item"),
        "Replenishment Execution History": ("started_at","trigger_type","status","created"),
        "Reorder Execution History": ("scheduled_date","status","attempts"),
        "Reorder Calculation History": ("item_code","status","calculation_date","recommended_level","recommended_qty"),
    }
    if name in list_columns:
        for f in existing.values():
            if f.fieldtype not in ("Section Break","Column Break","HTML","Table"):
                f.in_list_view=int(f.fieldname in list_columns[name] and not f.hidden)
    if name=="Reorder Calculation History":
        for k in ("calculation_key","batch"):
            existing[k].hidden=1
            existing[k].in_list_view=0
        existing["status"].in_list_view=1
        existing["calculation_date"].in_list_view=1
    doc.set("fields",ordered)
    for idx, field in enumerate(doc.fields, 1):
        field.idx = idx
    doc.save()
    frappe.clear_cache(doctype=name)
