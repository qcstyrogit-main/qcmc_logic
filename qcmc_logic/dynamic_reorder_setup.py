"""Explicit configuration schema for Dynamic Reorder; installed by approved migration."""
import frappe

CATEGORIES = "Finished Goods\nRaw Materials\nFactory Supplies\nOffice Supplies\nMaintenance Stock Room"
def field(name, kind="Data", options=None, default=None, reqd=0):
    result = {"fieldname": name, "label": name.replace("_", " ").title(), "fieldtype": kind, "reqd": reqd}
    if options is not None: result["options"] = options
    if default is not None: result["default"] = str(default)
    return result

def check(name, default=0): return field(name, "Check", default=default)
def link(name, target, required=0): return field(name, "Link", target, reqd=required)
def num(name, default=0, kind="Float"): return field(name, kind, default=default)

SCHEMAS = {
    "Reorder Execution History": [
        field("scheduled_date","Date",reqd=1),field("status"),num("attempts",0,"Int"),
        check("catch_up"),field("started_at","Datetime"),field("finished_at","Datetime"),
        field("details","Long Text"),field("last_error","Small Text")],
    "Reorder Settings": [
        check("enabled"), check("automatic_update_enabled"), check("preview_only",1), check("allow_new_reorder_rows"), field("first_scheduled_date","Date"),check("email_execution_alerts")],
    "Seasonal Demand Profile": [
        field("profile_name", reqd=1), field("mode","Select","Disabled\nManual\nAutomatic","Disabled"),
        num("history_months",36,"Int")] + [num("month_"+str(i),1) for i in range(1,13)],
    "Reorder Policy": [
        field("policy_name",reqd=1), field("inventory_category","Select",CATEGORIES,"Finished Goods",1),
        check("enabled"), link("inventory_type","Inventory Type",1),
        field("demand_period_method","Select","Complete Calendar Months\nRolling Days\nMonth-to-Date Inclusive","Complete Calendar Months"),
        num("rolling_days",90,"Int"), num("historical_months",3,"Int"), num("lead_time",7,"Int"),
        num("safety_days",5,"Int"), num("coverage_days",15,"Int"), num("minimum_stock"),
        num("maximum_stock"), num("overstock_coverage_days",90,"Int"), num("moq"), num("order_multiple"), num("production_batch"),
        field("material_request_type","Select","Preserve\nManufacture\nPurchase","Preserve"),
        link("seasonal_profile","Seasonal Demand Profile"), check("preserve_no_demand",1),
        check("deduct_returns",1), num("increase_limit",30), num("decrease_limit",20),
        check("automatic_update_enabled"), check("approval_required",1), check("allow_new_reorder_rows"), field("remarks","Small Text")],
    "Reorder Policy Mapping": [
        check("enabled"), link("policy","Reorder Policy",1), link("company","Company",1),
        link("item_code","Item"), link("item_group","Item Group"), check("include_item_descendants"),
        link("warehouse","Warehouse"), check("include_warehouse_descendants"),
        num("priority",0,"Int"), field("effective_from","Date"), field("effective_to","Date")],
    "Item Reorder Override": [
        check("enabled",1), check("exclude_item",1), link("company","Company",1), link("item_code","Item",1),
        link("warehouse","Warehouse",1), link("policy","Reorder Policy"),
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
        link("policy","Reorder Policy"), field("reorder_row"), check("created_reorder_row"), field("status"),
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
    for name, fields in SCHEMAS.items():
        if frappe.db.exists("DocType", name):
            continue
        history = name.endswith("Calculation History")
        settings = name.endswith("Settings")
        # Initially restrict the entire feature to System Manager. Scoped access is
        # intentionally not granted until report and document permissions are verified.
        permissions = [{"role":"System Manager","read":1,"write":0 if history else 1,
                        "create":0 if history else 1,"delete":0,"export":1}]
        if history:
            fields = [dict(f, read_only=1, **({"unique":1} if f["fieldname"] in ("calculation_key","scheduled_date") else {})) for f in fields]
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
    configure_reference_titles()
    from qcmc_logic.dynamic_reorder_titles import install_titles
    install_titles()
    install_workspace()
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

