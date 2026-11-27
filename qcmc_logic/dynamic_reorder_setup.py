"""Explicit configuration schema for Dynamic Reorder; installed by approved migration."""
import frappe

def field(name, kind="Data", options=None, default=None, reqd=0):
    result = {"fieldname": name, "label": name.replace("_", " ").title(), "fieldtype": kind, "reqd": reqd}
    if options is not None: result["options"] = options
    if default is not None: result["default"] = str(default)
    return result

def check(name, default=0): return field(name, "Check", default=default)
def link(name, target, required=0): return field(name, "Link", target, reqd=required)
def num(name, default=0, kind="Float"): return field(name, kind, default=default)

SCHEMAS = {
    "Reorder Calculation Batch": [
        field("display_title"),link("company","Company"),link("mapping","Reorder Policy Mapping"),
        link("warehouse","Warehouse"),field("calculation_date","Date"),field("trigger_type"),link("calculated_by","User"),
        field("status"),num("total_items",0,"Int"),num("pending_items",0,"Int"),num("unchanged_items",0,"Int"),
        num("review_items",0,"Int"),num("failed_items",0,"Int"),num("approved_items",0,"Int"),num("reverted_items",0,"Int"),
        field("parameters","Long Text"),field("last_error","Small Text"),field("results_table","HTML")],
    "Reorder Calculation Item": [
        link("batch","Reorder Calculation Batch",1),link("item_code","Item",1),field("status"),
        num("previous_level"),num("previous_qty"),num("recommended_level"),num("recommended_qty"),num("projected_qty"),
        field("reason","Small Text"),field("snapshot","Long Text"),link("approval_history","Reorder Calculation History")],
    "Reorder Schedule Settings": [
        check("enabled",1),field("frequency","Select","Daily\nWeekly\nMonthly","Monthly",1),
        field("execution_weekday","Select","Monday\nTuesday\nWednesday\nThursday\nFriday\nSaturday\nSunday","Monday",1),
        num("day_of_month",1,"Int"),field("execution_time","Time",default="02:00:00",reqd=1),
        num("maximum_retry_attempts",3,"Int"),check("recover_missed_executions",1),
        field("effective_from","Date"),field("schedule_overview","HTML")],
    "Replenishment Execution History": [
        field("trigger_type","Select","Manual\nScheduled"),link("triggered_by","User"),link("mapping","Reorder Policy Mapping"),
        field("started_at","Datetime"),field("finished_at","Datetime"),field("status"),
        num("checked",0,"Int"),num("created",0,"Int"),num("skipped",0,"Int"),num("failed",0,"Int"),
        field("details","Long Text"),field("last_error","Small Text")],
    "Reorder Execution History": [
        field("scheduled_date","Date",reqd=1),field("execution_key"),field("status"),num("attempts",0,"Int"),
        check("catch_up"),field("started_at","Datetime"),field("finished_at","Datetime"),
        field("details","Long Text"),field("last_error","Small Text")],
    "Reorder Settings": [
        check("enabled"), check("automatic_update_enabled"), check("preview_only",1), check("allow_new_reorder_rows"), field("first_scheduled_date","Date"),check("email_execution_alerts"),
        field("replenishment_mode","Select","Disabled\nManual Draft\nAutomatic Draft","Disabled"),field("operational_overview","HTML")],
    "Seasonal Demand Profile": [
        field("profile_name", reqd=1), field("mode","Select","Disabled\nManual\nAutomatic","Disabled"),
        num("history_months",36,"Int")] + [num("month_"+str(i),1) for i in range(1,13)],
    "Reorder Policy": [
        field("policy_name",reqd=1), field("inventory_category","Link","Inventory Group","FG",1),
        check("enabled"), link("inventory_type","Inventory Type",1),
        field("demand_period_method","Select","Complete Calendar Months\nRolling Days\nMonth-to-Date Inclusive","Complete Calendar Months"),
        num("rolling_days",90,"Int"), num("historical_months",3,"Int"), num("lead_time",7,"Int"),
        num("safety_days",5,"Int"), num("coverage_days",15,"Int"), num("minimum_stock"),
        num("maximum_stock"), num("overstock_coverage_days",90,"Int"), num("moq"), num("order_multiple"), num("production_batch"),
        field("material_request_type","Select","Preserve\nManufacture\nPurchase","Preserve"),
        link("seasonal_profile","Seasonal Demand Profile"), check("preserve_no_demand",1),
        check("demand_delivery",1),check("demand_manufacture",1),check("demand_intercompany",1),check("demand_provincial",1),
        check("deduct_returns",1), num("increase_limit",30), num("decrease_limit",20),
        check("automatic_update_enabled"), check("approval_required",1), check("allow_new_reorder_rows"), field("remarks","Small Text")],
    "Reorder Policy Mapping": [
        field("mapping_name"),link("inventory_group","Inventory Group"),link("inventory_type","Inventory Type"),
        check("legacy_scope_reviewed"),check("migration_review_required"),field("migration_note","Small Text"),
        field("warehouses","Table","Reorder Mapping Warehouse"),link("replenishment_warehouse","Warehouse"),
        check("automatic_draft_replenishment"),
        check("enabled"), link("policy","Reorder Policy",1), link("company","Company",1),
        link("item_code","Item"), link("item_group","Item Group"), check("include_item_descendants"),
        link("warehouse","Warehouse"), check("include_warehouse_descendants"),
        num("priority",0,"Int"), field("effective_from","Date"), field("effective_to","Date")],
    "Item Reorder Override": [
        check("enabled",1), check("exclude_item",0), link("company","Company",1), link("item_code","Item",1),
        link("warehouse","Warehouse"), link("mapping","Reorder Policy Mapping"), link("policy","Reorder Policy"),check("legacy_scope_reviewed"),
        field("production_mode","Select","Make to Stock\nMake to Order\nHybrid","Make to Order"),
        check("allow_make_to_order"), check("override_parameters"), num("historical_months",3,"Int"),
        num("lead_time",7,"Int"), num("safety_days",5,"Int"), num("coverage_days",15,"Int"),
        num("minimum_stock"), num("maximum_stock"), num("moq"), num("order_multiple"), num("production_batch"),
        check("override_seasonal_profile"), link("seasonal_profile","Seasonal Demand Profile"),
        check("fixed_reorder_values"), num("fixed_reorder_level"), num("fixed_reorder_qty"),
        field("effective_from","Date"), field("effective_to","Date"),
        field("reason","Small Text",reqd=1)],
    "Reorder Calculation History": [
        field("calculation_key",reqd=1), field("batch"), field("calculation_date","Date"),
        link("company","Company"), link("item_code","Item"), link("warehouse","Warehouse"),
        link("policy","Reorder Policy"), link("mapping","Reorder Policy Mapping"), field("reorder_row"), check("created_reorder_row"), field("status"),
        num("previous_level"), num("previous_qty"), num("recommended_level"), num("recommended_qty"),
        num("actual_qty"), num("projected_qty"), field("details","Long Text"), field("reason","Small Text"),
        link("applied_by","User"), field("applied_at","Datetime")]
}

def rename_before_migrate():
    from qcmc_logic.dynamic_reorder_layout import rename_existing
    rename_public_names()
    rename_existing(SCHEMAS)

def rename_public_names():
    """Rename existing metadata without dropping configuration or history."""
    pairs = [
        ("DocType", "Dynamic Reorder Settings", "Reorder Settings"),
        ("DocType", "QCMC Dynamic Reorder Settings", "Reorder Settings"),
        ("Report", "Dynamic Reorder Analysis", "Reorder Analysis"),
        ("Workspace", "Dynamic Reorder Management", "Reorder Management"),
        ("Workspace Sidebar", "Dynamic Reorder Management", "Reorder Management"),
        ("Desktop Icon", "Dynamic Reorder Management", "Reorder Management"),
    ]
    for dt, old, new in pairs:
        if frappe.db.exists(dt, old) and frappe.db.exists(dt, new):
            frappe.throw("Reorder naming conflict: " + dt + " / " + new)
    if all(frappe.db.exists("DocType", n) for n in ("Dynamic Reorder Settings", "QCMC Dynamic Reorder Settings")):
        frappe.throw("Multiple legacy reorder settings found")
    for dt, old, new in pairs:
        if not frappe.db.exists(dt, old):
            continue
        saved = frappe.db.get_singles_dict(old) if dt=="DocType" else None
        if dt == "Workspace Sidebar" and not frappe.db.get_value(dt, old, "app"):
            frappe.db.set_value(dt, old, "app", "qcmc_logic", update_modified=False)
        frappe.rename_doc(dt, old, new, force=True, rebuild_search=False)
        if saved is not None:
            for field in ("enabled","preview_only","automatic_update_enabled","allow_new_reorder_rows"):
                if field in saved:
                    frappe.db.set_single_value(new, field, saved[field])
        for field in {"Report":("report_name",), "Workspace":("title","label"), "Workspace Sidebar":("title",), "Desktop Icon":("label","sidebar","link_to")}.get(dt,()):
            if frappe.get_meta(dt).has_field(field):
                frappe.db.set_value(dt,new,field,new,update_modified=False)
        if dt=="DocType":
            frappe.clear_cache(doctype=old)
            frappe.clear_cache(doctype=new)

def install():
    """No default mappings or automatic activation. Never overwrite existing definitions."""
    from qcmc_logic.dynamic_reorder_layout import rename_existing, layout
    rename_public_names()
    rename_existing(SCHEMAS)
    from qcmc_logic.dynamic_reorder_v2_setup import install_child
    install_child()
    for name, fields in SCHEMAS.items():
        if frappe.db.exists("DocType", name):
            continue
        history = name.endswith("History") or name in ("Reorder Calculation Batch","Reorder Calculation Item")
        settings = name.endswith("Settings")
        # Initially restrict the entire feature to System Manager. Scoped access is
        # intentionally not granted until report and document permissions are verified.
        permissions = [{"role":"System Manager","read":1,"write":0 if history else 1,
                        "create":0 if history else 1,"delete":0,"export":1}]
        if history:
            fields = [dict(f, read_only=1, **({"unique":1} if f["fieldname"] in ("calculation_key","execution_key") else {})) for f in fields]
        doc = frappe.get_doc({"doctype":"DocType","name":name,"module":"QCMC Logics",
            "custom":1,"issingle":int(settings),"autoname":"hash" if not settings else "",
            "track_changes":1,"fields":fields,"permissions":permissions})
        doc.insert()
    for name, fields in SCHEMAS.items():
        layout(name, fields)
    from qcmc_logic.dynamic_reorder_clock import business_now
    from qcmc_logic.dynamic_reorder_scheduler import next_month
    if not frappe.db.get_single_value("Reorder Settings","first_scheduled_date"):
        frappe.db.set_single_value("Reorder Settings","first_scheduled_date",next_month(business_now().date()))
    from qcmc_logic.dynamic_reorder_schedule import initialize, backfill_execution_keys
    backfill_execution_keys()
    initialize()
    from qcmc_logic.dynamic_reorder_v2_setup import install_fields
    install_fields()
    configure_reference_titles()
    batch_meta=frappe.get_doc("DocType","Reorder Calculation Batch")
    batch_meta.title_field="display_title"
    batch_meta.show_title_field_in_link=1
    batch_meta.save()
    frappe.db.add_index("Reorder Calculation Item",["batch","item_code"])
    frappe.db.add_index("Reorder Calculation Item",["batch","status"])
    from qcmc_logic.dynamic_reorder_titles import install_titles
    install_titles()
    install_workspace()
    organize_schedule_workspace()
    install_search_navigation()

def install_search_navigation():
    name = "Reorder Management"
    if not frappe.db.exists("Workspace", name):
        return
    if not frappe.db.exists("Workspace Sidebar", name):
        frappe.get_doc({
            "doctype": "Workspace Sidebar", "title": name,
            "module": "QCMC Logics", "app": "qcmc_logic", "header_icon": "package",
            "for_user": "Administrator",
            "items": [{"label": name, "type": "Link",
                       "link_type": "Workspace", "link_to": name}]
        }).insert(ignore_permissions=True)
    if not frappe.db.exists("Desktop Icon", name):
        frappe.get_doc({
            "doctype": "Desktop Icon", "label": name,
            "icon_type": "Link", "link_type": "Workspace Sidebar",
            "link_to": name, "sidebar": name, "owner": "Administrator",
            "standard": 0, "hidden": 0, "icon": "package",
            "roles": [{"role": "System Manager"}]
        }).insert(ignore_permissions=True)
    from frappe.desk.doctype.desktop_icon.desktop_icon import clear_desktop_icons_cache
    clear_desktop_icons_cache("Administrator")

def configure_reference_titles():
    for name, title in (
        ("Reorder Policy", "policy_name"),
        ("Seasonal Demand Profile", "profile_name"),
    ):
        doc = frappe.get_doc("DocType", name)
        if doc.title_field != title or not doc.show_title_field_in_link or doc.search_fields != title:
            doc.title_field = title
            doc.show_title_field_in_link = 1
            doc.search_fields = title
            doc.save()
            frappe.clear_cache(doctype=name)

def install_workspace():
    import json
    name = "Reorder Management"
    if frappe.db.exists("Workspace", name):
        workspace = frappe.get_doc("Workspace", name)
        changed = False
        renames = {"Dynamic Reorder Settings":"Reorder Settings","Dynamic Reorder Analysis":"Reorder Analysis","Dynamic Reorder Management":"Reorder Management"}
        for old, new in renames.items():
            if old in (workspace.content or ""):
                workspace.content = workspace.content.replace(old,new)
                changed = True
        for shortcut in workspace.shortcuts:
            for field in ("label","link_to"):
                if shortcut.get(field) in renames:
                    shortcut.set(field,renames[shortcut.get(field)])
                    changed=True
            if shortcut.link_to and shortcut.link_to.startswith("QCMC ") and shortcut.link_to[5:] in SCHEMAS:
                shortcut.link_to=shortcut.link_to[5:]
                changed=True
            if shortcut.report_ref_doctype == "QCMC Reorder Calculation History":
                shortcut.report_ref_doctype="Reorder Calculation History"
                changed=True
        if not any(s.link_to=="Reorder Execution History" for s in workspace.shortcuts):
            workspace.append("shortcuts", {"type":"DocType","link_to":"Reorder Execution History","label":"Reorder Execution History","doc_view":"List"})
            blocks=json.loads(workspace.content or "[]")
            blocks.append({"id":"dr-execution","type":"shortcut","data":{"shortcut_name":"Reorder Execution History","col":4}})
            workspace.content=json.dumps(blocks)
            changed=True
        if changed:
            workspace.save()
        if frappe.db.exists("Report", "Reorder Analysis") and not any(s.link_to=="Reorder Analysis" for s in workspace.shortcuts):
            workspace.append("shortcuts", {"type":"Report","link_to":"Reorder Analysis","label":"Reorder Analysis","report_ref_doctype":"Reorder Calculation History"})
            blocks = json.loads(workspace.content or "[]")
            blocks.append({"id":"dr-analysis","type":"shortcut","data":{"shortcut_name":"Reorder Analysis","col":4}})
            workspace.content=json.dumps(blocks)
            workspace.save()
        return
    shortcuts = []
    blocks = [{"id":"dr-title","type":"header","data":{"text":"<span class=\"h4\">Reorder Management</span>","col":12}}]
    for i, target in enumerate(SCHEMAS):
        label = target.removeprefix("QCMC ")
        shortcuts.append({"type":"DocType","link_to":target,"label":label,"doc_view":"List" if not target.endswith("Settings") else ""})
        blocks.append({"id":"dr-"+str(i),"type":"shortcut","data":{"shortcut_name":label,"col":4}})
    if frappe.db.exists("Report","Reorder Analysis"):
        shortcuts.append({"type":"Report","link_to":"Reorder Analysis","label":"Reorder Analysis","report_ref_doctype":"Reorder Calculation History"})
        blocks.append({"id":"dr-analysis","type":"shortcut","data":{"shortcut_name":"Reorder Analysis","col":4}})
    frappe.get_doc({"doctype":"Workspace","name":name,"label":name,"title":name,"module":"QCMC Logics",
        "public":1,"roles":[{"role":"System Manager"}],"content":json.dumps(blocks),"shortcuts":shortcuts}).insert()

def organize_schedule_workspace():
    """Arrange only the known reorder shortcuts; retain any unrelated blocks."""
    import json
    ws=frappe.get_doc("Workspace","Reorder Management")
    groups=[
        ("1. Daily operations — calculate, review, then replenish",["Reorder Analysis","Reorder Calculation Batch","Replenishment Monitoring","Replenishment Execution History"]),
        ("2. Initial setup — settings, policy, warehouse mapping",["Reorder Settings","Reorder Policy","Reorder Policy Mapping","Reorder Schedule Settings"]),
        ("3. Advanced configuration and audit",["Seasonal Demand Profile","Item Reorder Override","Reorder Execution History","Reorder Calculation History","Reorder Calculation Item"])]
    known={name for _,names in groups for name in names}
    if not any(s.link_to=="Reorder Schedule Settings" for s in ws.shortcuts):
        ws.append("shortcuts",{"type":"DocType","link_to":"Reorder Schedule Settings","label":"Reorder Schedule Settings","doc_view":""})
    if frappe.db.exists("Report","Replenishment Monitoring") and not any(s.link_to=="Replenishment Monitoring" for s in ws.shortcuts):
        ws.append("shortcuts",{"type":"Report","link_to":"Replenishment Monitoring","label":"Replenishment Monitoring","report_ref_doctype":"Reorder Policy Mapping"})
    for shortcut in ws.shortcuts:
        if shortcut.link_to=="Reorder Analysis":
            shortcut.report_ref_doctype="Reorder Policy Mapping"
    if frappe.db.exists("DocType","Replenishment Execution History") and not any(s.link_to=="Replenishment Execution History" for s in ws.shortcuts):
        ws.append("shortcuts",{"type":"DocType","link_to":"Replenishment Execution History","label":"Replenishment Execution History","doc_view":"List"})
    if not any(s.link_to=="Reorder Calculation Batch" for s in ws.shortcuts):
        ws.append("shortcuts",{"type":"DocType","link_to":"Reorder Calculation Batch","label":"Calculation Batches","doc_view":"List"})
    # Item results are accessed through the parent, not a workspace shortcut.
    ws.set("shortcuts",[s for s in ws.shortcuts if s.link_to!="Reorder Calculation Item"])
    by_name={s.link_to:s for s in ws.shortcuts}
    from qcmc_logic.dynamic_reorder_workspace import install_overview, BLOCK, BLOCK_ID
    blocks=[install_overview(ws)]
    for i,(label,names) in enumerate(groups):
        blocks.append({"id":"reorder-section-"+str(i),"type":"header","data":{"text":"<span class=\"h4\">"+label+"</span>","col":12}})
        for j,name in enumerate(names):
            if name in by_name:
                blocks.append({"id":"reorder-shortcut-"+str(i)+"-"+str(j),"type":"shortcut","data":{"shortcut_name":by_name[name].label,"col":4}})
    for block in json.loads(ws.content or "[]"):
        data=block.get("data",{})
        if block.get("id")==BLOCK_ID or data.get("custom_block_name")==BLOCK:
            continue
        if block.get("id","").startswith(("dr-title","reorder-section-","reorder-shortcut-")) or data.get("shortcut_name") in known:
            continue
        if block.get("type")=="header" and data.get("text") in ("<span class=\"h4\">Reorder Management</span>","Reorder Management"):
            continue
        blocks.append(block)
    ws.content=json.dumps(blocks)
    ws.save()
