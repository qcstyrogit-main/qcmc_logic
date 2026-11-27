"""Read-only V2 recommendations: one item, one mapping, one combined scope."""
from decimal import Decimal
import frappe
from frappe.utils import getdate, cint
from qcmc_logic.dynamic_reorder_clock import business_date
from qcmc_logic.dynamic_reorder_calculation import calculate, historical_months, seasonal_indices, demand_period, number
from qcmc_logic.dynamic_reorder_demand import monthly_demand, configured_sources
from qcmc_logic.dynamic_reorder_policy import (
    active_on, is_v2_mapping, mapping_warehouses, validate_scope, mapping_conflicts, production_mode,
)
from qcmc_logic.utils import check_warehouse_access, check_item_inventory_group_access


def require_admin():
    if frappe.session.user != "Administrator" or frappe.request and frappe.request.method != "POST":
        frappe.throw("Administrator POST access required", frappe.PermissionError)


def document_dict(doc):
    return doc.as_dict() if callable(getattr(doc,"as_dict",None)) else dict(doc)


def load_mapping(company, name, as_of):
    if not name:
        frappe.throw("Select a Reorder Policy Mapping; legacy warehouse previews require scope review")
    mapping = frappe.get_doc("Reorder Policy Mapping", name)
    if mapping.company != company:
        frappe.throw("Mapping must belong to the selected company")
    if not is_v2_mapping(mapping):
        frappe.throw("Legacy mapping scope requires explicit review before V2 preview")
    warehouses = {w.name:w for w in frappe.get_all("Warehouse", filters={"name":["in",mapping_warehouses(mapping)]},
        fields=["name","company","disabled","is_group"])}
    try:
        validate_scope(mapping, warehouses)
    except ValueError as exc:
        frappe.throw(str(exc))
    policy = frappe.get_doc("Reorder Policy", mapping.policy)
    scope = dict(document_dict(mapping),
                 inventory_group=policy.inventory_category, inventory_type=policy.inventory_type)
    # Fail closed even for records written before the validation hook was installed.
    for other in frappe.get_all("Reorder Policy Mapping", filters={"company":company,"enabled":1}, fields=["*"]):
        if other.name == mapping.name:
            continue
        other_policy = frappe.get_doc("Reorder Policy", other.policy)
        other.update(inventory_group=other_policy.inventory_category,inventory_type=other_policy.inventory_type)
        if mapping_conflicts(scope,other):
            frappe.throw("Overlapping active Reorder Policy Mapping: " + other.name)
    return mapping, policy


def preview_rows(company, warehouse=None, item_group=None, item_code=None, as_of=None,
                 period_method=None, rolling_days=None, mapping=None):
    """Legacy warehouse argument is accepted only as an additional scope check.

    It can never select or expand a V2 mapping. Stock is current Bin stock; as_of
    selects demand history, not a historical reconstruction of projected stock.
    """
    if frappe.session.user != "Administrator":
        frappe.throw("Administrator access required", frappe.PermissionError)
    today = business_date()
    as_of = getdate(as_of or today)
    if as_of > today:
        frappe.throw("Future calculation dates are not supported")
    config, base_policy = load_mapping(company,mapping,as_of)
    warehouses = mapping_warehouses(config)
    if warehouse and warehouse not in warehouses:
        frappe.throw("Warehouse is outside the selected mapping")
    if not active_on(config,as_of) or not base_policy.enabled:
        return []
    if not base_policy.inventory_category or not base_policy.inventory_type:
        frappe.throw("Mapping policy classification is incomplete")
    if not all(check_warehouse_access(frappe.session.user,w) for w in warehouses):
        frappe.throw("Access to every mapped warehouse is required",frappe.PermissionError)
    filters = dict(disabled=0,is_stock_item=1,has_variants=0,
        custom_inventory_group=base_policy.inventory_category,custom_inventory_type_=base_policy.inventory_type)
    if item_group: filters["item_group"] = item_group
    if item_code: filters["name"] = item_code
    items = frappe.get_all("Item",filters=filters,fields=["name","item_name","item_group","stock_uom",
        "end_of_life","creation","custom_inventory_type_","custom_inventory_group"],order_by="name")
    overrides = frappe.get_all("Item Reorder Override",filters={"mapping":mapping,"enabled":1},fields=["*"])
    by_override = {}
    for override in overrides:
        if active_on(override,as_of):
            by_override.setdefault(override.item_code,[]).append(override)
    stock, existing = {}, {}
    names = [i.name for i in items]
    for offset in range(0,len(names),500):
        chunk = names[offset:offset+500]
        for row in frappe.get_all("Bin",filters={"warehouse":["in",warehouses],"item_code":["in",chunk]},
                                  fields=["item_code","warehouse","actual_qty","projected_qty"]):
            value = stock.setdefault(row.item_code,dict(actual_qty=Decimal(0),projected_qty=Decimal(0)))
            for field in value:
                value[field] += number(row.get(field) or 0)
        for row in frappe.get_all("Item Reorder",filters={"parent":["in",chunk],"parenttype":"Item","parentfield":"reorder_levels"},fields=["*"]):
            existing.setdefault(row.parent,[]).append(row)
    profiles, demand_groups, prepared, result = {}, {}, [], []
    precision_cache = {}
    default_precision = cint(frappe.db.get_default("float_precision") or 3)
    for item in items:
        common = dict(schema_version=2,preview_only=True,company=company,mapping=mapping,
            mapping_name=config.get("mapping_name") or mapping,warehouses=warehouses,
            warehouse=config.replenishment_warehouse,replenishment_warehouse=config.replenishment_warehouse,
            item_code=item.name,item_name=item.item_name,item_group=item.item_group,stock_uom=item.stock_uom,
            policy=base_policy.name,production_mode=production_mode(base_policy.inventory_category))
        try:
            if (item.custom_inventory_group,item.custom_inventory_type_) != (base_policy.inventory_category,base_policy.inventory_type):
                continue
            if not check_item_inventory_group_access(frappe.session.user,item.name):
                continue
            if item.end_of_life and str(item.end_of_life) != "0000-00-00" and getdate(item.end_of_life) <= as_of:
                continue
            applicable = by_override.get(item.name,[])
            if len(applicable)>1:
                raise ValueError("Conflicting overrides for item and mapping")
            override = applicable[0] if applicable else frappe._dict()
            if override.get("warehouse") and not override.get("legacy_scope_reviewed"):
                raise ValueError("Legacy override warehouse scope requires explicit mapping-wide review")
            if override.get("company") and override.company != company:
                raise ValueError("Override company must match mapping company")
            if override.exclude_item:
                result.append(dict(common,status="Skipped",reason="Excluded by mapping-wide item override"))
                continue
            policy = frappe._dict(document_dict(base_policy))
            if override.policy:
                policy = frappe._dict(document_dict(frappe.get_doc("Reorder Policy",override.policy)))
                if (policy.inventory_category,policy.inventory_type) != (base_policy.inventory_category,base_policy.inventory_type):
                    raise ValueError("Override policy must retain mapping classification")
                if not policy.enabled:
                    raise ValueError("Override policy is disabled")
            if override.override_parameters:
                for field in ("historical_months","lead_time","safety_days","coverage_days","minimum_stock",
                              "maximum_stock","moq","order_multiple","production_batch"):
                    policy[field] = override.get(field)
            if override.override_seasonal_profile:
                policy.seasonal_profile = override.seasonal_profile
            owned = [r for r in existing.get(item.name,[]) if r.get("custom_reorder_mapping")==mapping]
            if len(owned)>1:
                raise ValueError("Duplicate managed Item Reorder rows for item and mapping")
            row = owned[0] if owned else frappe._dict(name=None,warehouse_reorder_level=0,warehouse_reorder_qty=0)
            if owned and (not row.get("custom_managed_reorder") or row.warehouse!=config.replenishment_warehouse or row.get("warehouse_group") not in (None,"",config.replenishment_warehouse)):
                raise ValueError("Managed Item Reorder configuration requires review")
            common.update(policy=policy.name,reorder_row=row.name,new_reorder_row=not owned,
                previous_level=row.warehouse_reorder_level or 0,previous_qty=row.warehouse_reorder_qty or 0,
                legacy_reorder_rows=[r.name for r in existing.get(item.name,[]) if r not in owned and
                    (r.warehouse in warehouses or r.get("warehouse_group"))],
                actual_qty=stock.get(item.name,{}).get("actual_qty",Decimal(0)),
                projected_qty=stock.get(item.name,{}).get("projected_qty",Decimal(0)),
                stock_as_of=str(today),material_request_type=policy.material_request_type,
                override=override.get("name"),policy_snapshot=dict(policy))
            method = period_method or policy.demand_period_method or "Complete Calendar Months"
            days = cint(rolling_days if rolling_days is not None else policy.rolling_days or 90)
            periods = demand_period(as_of,method,cint(policy.historical_months),days)
            if getdate(item.creation)>periods[0][0]:
                result.append(dict(common,status="Skipped",reason="Incomplete history for new item"))
                continue
            if policy.seasonal_profile and policy.seasonal_profile not in profiles:
                profiles[policy.seasonal_profile] = frappe.get_doc("Seasonal Demand Profile",policy.seasonal_profile)
            profile = profiles.get(policy.seasonal_profile)
            extended = historical_months(as_of,cint(profile.history_months)) if profile and profile.mode=="Automatic" else None
            sources = configured_sources(policy)
            demand_key = (periods[0][0],periods[-1][1],bool(policy.deduct_returns),sources)
            seasonal_key = (extended[0][0],extended[-1][1],bool(policy.deduct_returns),sources) if extended and getdate(item.creation)<=extended[0][0] else None
            for key in {demand_key,seasonal_key}-{None}:
                demand_groups.setdefault(key,set()).add(item.name)
            prepared.append((item,common,policy,override,method,days,periods,profile,extended,demand_key,seasonal_key))
        except (ValueError,ArithmeticError) as exc:
            result.append(dict(common,status="Failed",reason=str(exc)))
    demand_data = {}
    for key,names in demand_groups.items():
        start,end,deduct,sources = key
        data = {}; names = sorted(names)
        for offset in range(0,len(names),500):
            data.update(monthly_demand(company,warehouses,names[offset:offset+500],start,end,deduct,sources=sources))
        demand_data[key] = data
    for item,common,policy,override,method,days,periods,profile,extended,demand_key,seasonal_key in prepared:
        try:
            demand = demand_data[demand_key]
            def total(data, month, field="net"):
                return sum((number(data.get((item.name,w,month),{}).get(field,0)) for w in warehouses),Decimal(0))
            history = {m.replace(day=1):total(demand,m.replace(day=1)) for m,_ in periods}
            indices = None
            if profile and profile.mode=="Manual":
                indices = {m:profile.get("month_"+str(m)) for m in range(1,13)}
            elif seasonal_key:
                indices = seasonal_indices([(m,total(demand_data[seasonal_key],m)) for m,_ in extended])
            if item.stock_uom not in precision_cache:
                precision_cache[item.stock_uom] = 0 if frappe.db.get_value("UOM",item.stock_uom,"must_be_whole_number") else default_precision
            recommendation = calculate(as_of,history,lead=cint(policy.lead_time),safety=cint(policy.safety_days),
                coverage=cint(policy.coverage_days),minimum=policy.minimum_stock or 0,maximum=policy.maximum_stock or 0,
                moq=policy.moq or 0,multiple=policy.order_multiple or 0,batch=policy.production_batch or 0,
                precision=precision_cache[item.stock_uom],indices=indices,previous_level=common["previous_level"],
                previous_qty=common["previous_qty"],projected=common["projected_qty"],increase_limit=policy.increase_limit or 0,
                decrease_limit=policy.decrease_limit or 0,preserve_no_demand=bool(policy.preserve_no_demand),periods=periods)
            if override.fixed_reorder_values:
                level,qty = number(override.fixed_reorder_level or 0),number(override.fixed_reorder_qty or 0)
                if level<0 or qty<0:
                    raise ValueError("Fixed reorder values must be non-negative")
                recommendation.update(reorder_level=level,reorder_qty=qty,status="Pending Approval",
                    reason="Fixed mapping-wide item override; preview only",suggested_replenishment=
                    max(qty,level-common["projected_qty"]) if (level or qty) and common["projected_qty"]<=level else Decimal(0))
            if common["production_mode"]=="Make to Order":
                recommendation["suggested_replenishment"] = Decimal(0)
            result.append(dict(common,monthly_demand={str(k):v for k,v in history.items()},
                demand_sources=list(demand_key[3]),demand_period_method=method,rolling_days=days,
                period_segments=[(str(a),str(b)) for a,b in periods],historical_start=str(periods[0][0]),historical_end=str(periods[-1][1]),
                seasonal_indices=indices,lead_time=policy.lead_time,safety_days=policy.safety_days,coverage_days=policy.coverage_days,
                gross_demand=sum(total(demand,m.replace(day=1),"gross") for m,_ in periods),
                sales_returns=sum(total(demand,m.replace(day=1),"returns") for m,_ in periods),**recommendation))
        except (ValueError,ArithmeticError) as exc:
            result.append(dict(common,status="Failed",reason=str(exc)))
    return sorted(result,key=lambda r:r["item_code"])


@frappe.whitelist(methods=["POST"])
def preview(company, mapping, item_code=None, as_of=None):
    require_admin()
    return preview_rows(company,mapping=mapping,item_code=item_code,as_of=as_of)
