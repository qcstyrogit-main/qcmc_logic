"""Read-only Finished Goods preview service. No inventory mutations."""
from datetime import date
from decimal import Decimal
import frappe
from frappe.utils import getdate, cint
from qcmc_logic.dynamic_reorder_clock import business_date
from qcmc_logic.dynamic_reorder_calculation import calculate, historical_months, seasonal_indices, demand_period
from qcmc_logic.dynamic_reorder_demand import monthly_demand
from qcmc_logic.dynamic_reorder_policy import resolve_policy, eligible_category
from qcmc_logic.utils import check_warehouse_access, check_item_inventory_group_access

def require_admin():
    if frappe.session.user != "Administrator" or frappe.request and frappe.request.method != "POST":
        frappe.throw("Administrator POST access required", frappe.PermissionError)

def ancestors(doctype, name):
    bounds = frappe.db.get_value(doctype, name, ["lft","rgt"], as_dict=True)
    if not bounds:
        return [name]
    parents = frappe.get_all(doctype, filters={"lft":["<=",bounds.lft],"rgt":[">=",bounds.rgt]},
                             pluck="name", order_by="lft desc")
    return [name] + [p for p in parents if p != name]

def candidate_scope(mappings, warehouse, warehouse_groups, as_of):
    """Conservative prefilter: never discard a possible mapping winner or conflict."""
    codes, groups = set(), set()
    for mapping in mappings:
        if mapping.effective_from and getdate(mapping.effective_from)>as_of:
            continue
        if mapping.effective_to and getdate(mapping.effective_to)<as_of:
            continue
        code, group, wh = mapping.item_code, mapping.item_group, mapping.warehouse
        if wh and not (wh==warehouse or mapping.include_warehouse_descendants and wh in warehouse_groups):
            continue
        if code:
            if wh:
                codes.add(code)
            continue
        if group:
            groups.add(group)
            if mapping.include_item_descendants:
                bounds=frappe.db.get_value("Item Group",group,["lft","rgt"],as_dict=True)
                if bounds:
                    groups.update(frappe.get_all("Item Group",filters={"lft":[">=",bounds.lft],"rgt":["<=",bounds.rgt]},pluck="name"))
        elif wh:
            # Warehouse-wide mapping may match any item. Keep the full candidate set.
            return None
    return codes,groups

def candidate_items(filters, scope):
    fields=["name","item_name","item_group","stock_uom","end_of_life","creation","custom_inventory_type_","custom_inventory_group"]
    if scope is None:
        return frappe.get_all("Item",filters=filters,fields=fields)
    codes,groups=scope
    found={}
    for field,values in (("name",codes),("item_group",groups)):
        if field in filters:
            values=values & {filters[field]}
        values=sorted(values)
        for start in range(0,len(values),500):
            selected=dict(filters)
            selected[field]=["in",values[start:start+500]]
            for item in frappe.get_all("Item",filters=selected,fields=fields):
                found[item.name]=item
    return list(found.values())

def preview_rows(company, warehouse, item_group=None, item_code=None, as_of=None, period_method=None, rolling_days=None):
    # All callers currently require Administrator because aggregate demand and
    # history access rules for delegated roles have not yet been verified.
    if frappe.session.user != "Administrator":
        frappe.throw("Administrator access required", frappe.PermissionError)
    today = business_date()
    as_of = getdate(as_of or today)
    if as_of > today:
        frappe.throw("Future calculation dates are not supported")
    wh = frappe.db.get_value("Warehouse", warehouse, ["company","disabled","is_group"], as_dict=True)
    if not wh or wh.company != company or wh.disabled or wh.is_group:
        frappe.throw("Select an enabled leaf warehouse belonging to the company")
    mappings = frappe.get_all("Reorder Policy Mapping", filters={"company":company,"enabled":1}, fields=["*"])
    policies = {p.name:p for p in frappe.get_all("Reorder Policy",fields=["*"])}
    overrides = frappe.get_all("Item Reorder Override", filters={"company":company,"warehouse":warehouse,"enabled":1}, fields=["*"])
    filters = {"disabled":0,"is_stock_item":1,"has_variants":0}
    if item_group: filters["item_group"] = item_group
    if item_code: filters["name"] = item_code
    groups = ancestors("Warehouse",warehouse)
    items = candidate_items(filters,candidate_scope(mappings,warehouse,groups,as_of))
    if not items:
        return []
    by_item = {}
    names=[item.name for item in items]
    for offset in range(0,len(names),500):
        rows=frappe.get_all("Item Reorder",filters={"warehouse":warehouse,"parenttype":"Item","parentfield":"reorder_levels","parent":["in",names[offset:offset+500]]},fields=["*"])
        for row in rows:
            by_item.setdefault(row.parent,[]).append(row)
    result = []
    overrides_by_item = {}
    for override in overrides:
        overrides_by_item.setdefault(override.item_code, []).append(override)
    group_cache, profile_cache, precision_cache = {}, {}, {}
    default_precision = cint(frappe.db.get_default("float_precision") or 3)
    # Scope balances to candidate items in bounded batches.
    stock_by_item = {}
    item_names = [item.name for item in items]
    for start in range(0,len(item_names),500):
        for stock in frappe.get_all("Bin",filters={"warehouse":warehouse,"item_code":["in",item_names[start:start+500]]},
                                    fields=["item_code","actual_qty","projected_qty"]):
            stock_by_item[stock.item_code]=stock
    warehouse_allowed = check_warehouse_access(frappe.session.user,warehouse)
    prepared = []
    demand_groups = {}
    for item in items:
        if item.end_of_life and str(item.end_of_life) != "0000-00-00" and getdate(item.end_of_life) <= as_of:
            continue
        if not warehouse_allowed or not check_item_inventory_group_access(frappe.session.user,item.name):
            continue
        try:
            if item.item_group not in group_cache:
                group_cache[item.item_group] = ancestors("Item Group",item.item_group)
            mapping = resolve_policy(mappings,company,item.name,group_cache[item.item_group],warehouse,groups,as_of)
            if not mapping: continue
            policy = policies.get(mapping.policy)
            if not policy or not eligible_category(policy): continue
            applicable = [o for o in overrides_by_item.get(item.name,[]) if
                          (not o.effective_from or getdate(o.effective_from)<=as_of) and
                          (not o.effective_to or getdate(o.effective_to)>=as_of)]
            if len(applicable)!=1:
                reason = "Explicit production-mode override required" if not applicable else "Conflicting overrides"
                result.append(dict(item_code=item.name,warehouse=warehouse,status="Skipped",reason=reason))
                continue
            override=applicable[0]
            if override.exclude_item or (override.production_mode=="Make to Order" and not override.allow_make_to_order):
                continue
            if override.policy:
                policy=policies.get(override.policy)
                if not policy or not eligible_category(policy): continue
            # Explicit, locally verified classification is mandatory; no guess from item names.
            if not policy.inventory_type or item.custom_inventory_type_ != policy.inventory_type:
                result.append(dict(item_code=item.name,warehouse=warehouse,status="Skipped",
                    reason="Item inventory type does not match explicitly configured policy"))
                continue
            # Work on a per-item copy; never mutate shared policy defaults.
            policy=frappe._dict(dict(policy))
            if override.override_parameters:
                for field in ("historical_months","lead_time","safety_days","coverage_days","minimum_stock",
                              "maximum_stock","moq","order_multiple","production_batch"):
                    policy[field]=override.get(field)
            if override.override_seasonal_profile:
                policy.seasonal_profile=override.seasonal_profile
            if override.fixed_reorder_values:
                result.append(dict(item_code=item.name,warehouse=warehouse,status="Skipped",
                    reason="Fixed reorder values protected from dynamic updates"))
                continue
            existing=by_item.get(item.name,[])
            if len(existing)>1 or (existing and existing[0].warehouse_group and existing[0].warehouse_group != warehouse):
                result.append(dict(item_code=item.name,item_name=item.item_name,warehouse=warehouse,status="Skipped",
                    reason="Duplicate Item Reorder rows" if len(existing)>1 else "Grouped warehouse configuration requires review"))
                continue
            new_row=not existing
            row=existing[0] if existing else frappe._dict(name=None,warehouse_reorder_level=0,warehouse_reorder_qty=0,
                material_request_type=policy.material_request_type if policy.material_request_type!="Preserve" else "Not configured")
            method=period_method or policy.demand_period_method or "Complete Calendar Months"
            days=cint(rolling_days if rolling_days is not None else (policy.rolling_days or 90))
            months=demand_period(as_of,method,cint(policy.historical_months),days)
            if getdate(item.creation)>months[0][0]:
                result.append(dict(item_code=item.name,warehouse=warehouse,status="Skipped",reason="Incomplete history for new item"))
                continue
            if policy.seasonal_profile and policy.seasonal_profile not in profile_cache:
                profile_cache[policy.seasonal_profile]=frappe.get_doc("Seasonal Demand Profile",policy.seasonal_profile)
            profile=profile_cache.get(policy.seasonal_profile)
            extended=historical_months(as_of,cint(profile.history_months)) if profile and profile.mode=="Automatic" else months
            demand_key=(months[0][0],months[-1][1],bool(policy.deduct_returns))
            seasonal_key=None
            if profile and profile.mode=="Automatic" and getdate(item.creation)<=extended[0][0]:
                seasonal_key=(extended[0][0],extended[-1][1],bool(policy.deduct_returns))
            prepared.append((item,policy,row,new_row,method,days,months,profile,extended,demand_key,seasonal_key))
            for group_key in {demand_key,seasonal_key}-{None}:
                demand_groups.setdefault(group_key,set()).add(item.name)
        except (ValueError, ArithmeticError) as exc:
            result.append(dict(item_code=item.name,warehouse=warehouse,status="Failed",reason=str(exc)))
    # Exact date bounds and return treatment define each compatible batch.
    demand_data={}
    for group_key,names in demand_groups.items():
        start,end,deduct=group_key
        names=sorted(names)
        aggregated={}
        for offset in range(0,len(names),500):
            aggregated.update(monthly_demand(company,[warehouse],names[offset:offset+500],start,end,deduct))
        demand_data[group_key]=aggregated
    for item,policy,row,new_row,method,days,months,profile,extended,demand_key,seasonal_key in prepared:
        try:
            demand=demand_data[demand_key]
            net=lambda m: demand.get((item.name,warehouse,m.replace(day=1)),{}).get("net",Decimal(0))
            history={m.replace(day=1):net(m) for m,_ in months}
            indices=None
            if profile and profile.mode=="Manual":
                indices={m:profile.get("month_"+str(m)) for m in range(1,13)}
            elif profile and profile.mode=="Automatic" and getdate(item.creation)<=extended[0][0]:
                seasonal_data=demand_data[seasonal_key]
                indices=seasonal_indices([(m,seasonal_data.get((item.name,warehouse,m),{}).get("net",Decimal(0))) for m,_ in extended])
            stock=stock_by_item.get(item.name,{})
            if item.stock_uom not in precision_cache:
                precision_cache[item.stock_uom]=0 if frappe.db.get_value("UOM",item.stock_uom,"must_be_whole_number") else default_precision
            precision=precision_cache[item.stock_uom]
            recommendation=calculate(as_of,history,lead=cint(policy.lead_time),safety=cint(policy.safety_days),
                coverage=cint(policy.coverage_days),minimum=policy.minimum_stock or 0,maximum=policy.maximum_stock or 0,
                moq=policy.moq or 0,multiple=policy.order_multiple or 0,batch=policy.production_batch or 0,
                precision=precision,indices=indices,previous_level=row.warehouse_reorder_level or 0,
                previous_qty=row.warehouse_reorder_qty or 0,projected=stock.get("projected_qty") or 0,
                increase_limit=policy.increase_limit or 0,decrease_limit=policy.decrease_limit or 0,
                preserve_no_demand=bool(policy.preserve_no_demand),periods=months)
            if new_row and "reorder_level" in recommendation:
                recommendation["status"]="New Reorder Configuration"
                recommendation["reason"]="No existing reorder row; manual approval required. " + recommendation.get("reason","")
                if row.material_request_type=="Not configured":
                    recommendation["reason"] += " Select an explicit Material Request Type before applying."
            if method!="Complete Calendar Months" and recommendation["status"]=="Preview":
                recommendation["status"]="Pending Approval"
                recommendation["reason"]="Non-calendar demand period requires manual review"
            result.append(dict(item_code=item.name,item_name=item.item_name,item_group=item.item_group,warehouse=warehouse,
                company=company,stock_uom=item.stock_uom,policy=policy.name,reorder_row=row.name,new_reorder_row=new_row,
                previous_level=row.warehouse_reorder_level,previous_qty=row.warehouse_reorder_qty,
                actual_qty=stock.get("actual_qty") or 0,projected_qty=stock.get("projected_qty") or 0,
                material_request_type=row.material_request_type,monthly_demand={str(k):v for k,v in history.items()},
                lead_time=policy.lead_time,safety_days=policy.safety_days,coverage_days=policy.coverage_days,
                policy_snapshot=dict(policy), seasonal_indices=indices, demand_period_method=method,
                period_segments=[(str(a),str(b)) for a,b in months], rolling_days=days,
                historical_start=str(months[0][0]), historical_end=str(months[-1][1]),
                gross_demand=sum(demand.get((item.name,warehouse,m.replace(day=1)),{}).get("gross",Decimal(0)) for m,_ in months),
                sales_returns=sum(demand.get((item.name,warehouse,m.replace(day=1)),{}).get("returns",Decimal(0)) for m,_ in months),
                **recommendation))
        except (ValueError, ArithmeticError) as exc:
            result.append(dict(item_code=item.name,warehouse=warehouse,status="Failed",reason=str(exc)))
    return result

@frappe.whitelist(methods=["POST"])
def preview(company, warehouse, item_group=None, item_code=None, as_of=None):
    require_admin()
    return preview_rows(company,warehouse,item_group,item_code,as_of)
