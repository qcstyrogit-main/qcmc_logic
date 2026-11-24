"""Read-only load benchmark using actual item/stock/demand data and simulated policies."""
from collections import Counter
from datetime import timedelta
from time import perf_counter
import tracemalloc
from unittest.mock import patch
import frappe
from frappe.utils import getdate, nowdate
from qcmc_logic import dynamic_reorder_service as service
from qcmc_logic.dynamic_reorder_audit import SETTINGS, HISTORY

def run(demand_heavy=False):
    if frappe.local.site!="erp.qcstyro.local" or frappe.session.user!="Administrator":
        frappe.throw("Local Administrator only")
    settings=frappe.get_single(SETTINGS)
    assert settings.enabled and settings.preview_only and not settings.automatic_update_enabled
    company,warehouse="QC Styropackaging Corporation","FG - Sta Clara"
    as_of=getdate(nowdate())
    original_get_all=frappe.get_all
    original_candidates=service.candidate_items
    fields=["name","item_group","custom_inventory_type_","creation","end_of_life"]
    sample=original_get_all("Item",filters={"disabled":0,"is_stock_item":1,"has_variants":0,"custom_inventory_group":"FG","creation":["<",as_of-timedelta(days=90)]},fields=fields,order_by="name",limit_page_length=0)
    sample=[i for i in sample if i.custom_inventory_type_ and (not i.end_of_life or str(i.end_of_life)=="0000-00-00" or getdate(i.end_of_life)>as_of)]
    assert sample,"No eligible sample items"
    policy_template=original_get_all("Reorder Policy",filters={"enabled":1,"inventory_category":"Finished Goods"},fields=["*"],limit_page_length=1)[0]
    before={d:frappe.db.count(d) for d in ("Item Reorder","Reorder Policy","Reorder Policy Mapping","Item Reorder Override",HISTORY)}
    output=[]
    from decimal import Decimal
    from qcmc_logic.dynamic_reorder_calculation import demand_period
    real_demand=service.monthly_demand
    def simulated_demand(company,warehouses,items,start,end,deduct_returns=True):
        periods=demand_period(as_of,"Rolling Days",3,90)
        return {(item,wh,m.replace(day=1)):{"gross":Decimal(1000),"returns":Decimal(50),"net":Decimal(950 if deduct_returns else 1000)} for item in items for wh in warehouses for m,_ in periods}
    demand_source=simulated_demand if demand_heavy else real_demand
    for n in sorted({min(len(sample),n) for n in (100,500,1000)}):
        chosen=sample[:n]
        names={i.name for i in chosen}
        policies={}
        overrides=[]
        for i in chosen:
            typ=i.custom_inventory_type_
            if typ not in policies:
                p=frappe._dict(dict(policy_template))
                p.update(name="LOAD-TEST-"+typ,inventory_type=typ,seasonal_profile=None,historical_months=3,automatic_update_enabled=0,approval_required=1,allow_new_reorder_rows=0)
                policies[typ]=p
            overrides.append(frappe._dict(item_code=i.name,company=company,warehouse=warehouse,enabled=1,exclude_item=0,production_mode="Make to Stock",policy=policies[typ].name))
        policy=next(iter(policies.values()))
        def mapping(**kw):
            row=frappe._dict(enabled=1,company=company,warehouse=warehouse,policy=policy.name,priority=0)
            row.update(kw)
            return row
        def scoped_candidates(filters,scope):
            # Preserve production candidate filtering; bound warehouse-wide scans to sample.
            filters=dict(filters)
            if "name" in filters:
                if filters["name"] not in names:
                    return []
                return original_candidates(filters,scope)
            found=[]
            for offset in range(0,n,500):
                chunk=set(i.name for i in chosen[offset:offset+500])
                if scope is None:
                    found.extend(original_candidates(filters,(chunk,set())))
                else:
                    codes,groups=scope
                    matched={i.name for i in chosen[offset:offset+500] if i.name in codes or i.item_group in groups}
                    found.extend(original_candidates(filters,(matched,set())))
            return found
        mappings=[mapping()]
        def test_get_all(doctype,*args,**kwargs):
            if doctype=="Reorder Policy Mapping": return mappings
            if doctype=="Reorder Policy": return list(policies.values())
            if doctype=="Item Reorder Override": return overrides
            return original_get_all(doctype,*args,**kwargs)
        def measure(label):
            tracemalloc.start()
            start=perf_counter()
            try:
                with patch.object(frappe,"get_all",side_effect=test_get_all), patch.object(service,"candidate_items",side_effect=scoped_candidates), patch.object(service,"monthly_demand",wraps=demand_source) as calls:
                    rows=service.preview_rows(company,warehouse,as_of=as_of,period_method="Rolling Days",rolling_days=90)
                    count=calls.call_count
                elapsed=perf_counter()-start
                _,peak=tracemalloc.get_traced_memory()
            finally:
                tracemalloc.stop()
            assert len(rows)==n and {r["item_code"] for r in rows}==names,(label,n,len(rows))
            statuses=Counter(r["status"] for r in rows)
            assert not statuses.get("Failed"),statuses
            if demand_heavy:
                calculated=sum("reorder_level" in r and "reorder_qty" in r for r in rows)
                assert calculated>=n*0.9,(n,calculated,statuses)
            else:
                calculated=sum("reorder_level" in r and "reorder_qty" in r for r in rows)
            output.append(dict(test=label,items=n,seconds=round(elapsed,3),python_peak_mib=round(peak/1048576,2),demand_batch_calls=count,statuses=dict(statuses),calculated=calculated,demand_source="simulated positive demand" if demand_heavy else "actual stock ledger"))
            return {r["item_code"]:r for r in rows}
        base=measure("Warehouse-wide mapping (bounded sample)")
        mappings=[mapping(item_group=g) for g in sorted({i.item_group for i in chosen})]
        grouped=measure("Item Group mappings")
        assert base==grouped,"Group and warehouse recommendations differ"
        # Exact item mapping wins; equal-priority duplicate must fail closed.
        first=chosen[0]
        parents=service.ancestors("Item Group",first.item_group)
        warehouse_parents=service.ancestors("Warehouse",warehouse)
        parent=parents[-1]
        mappings=[mapping(item_group=parent,include_item_descendants=1)]
        scope=service.candidate_scope(mappings,warehouse,warehouse_parents,as_of)
        assert scope is not None and first.item_group in scope[1]
        assert service.resolve_policy(mappings,company,first.name,parents,warehouse,warehouse_parents,as_of)==mappings[0]
        exact=mapping(item_code=first.name,priority=10)
        mappings.append(exact)
        assert service.resolve_policy(mappings,company,first.name,parents,warehouse,warehouse_parents,as_of)==exact
        mappings.append(frappe._dict(dict(exact)))
        try:
            service.resolve_policy(mappings,company,first.name,parents,warehouse,warehouse_parents,as_of)
        except ValueError:
            pass
        else:
            raise AssertionError("Duplicate mapping conflict not rejected")
        output.append(dict(items=n,result="PASS: identical recommendations, descendant scope, priority and conflict protection"))
        print("Completed load sample:",n,flush=True)
    assert before=={d:frappe.db.count(d) for d in before}
    output.append(dict(available_items=len(sample),result="PASS: no policy, reorder or history records added or removed"))
    return output
