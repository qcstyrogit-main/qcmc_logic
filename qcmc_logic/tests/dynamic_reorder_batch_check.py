"""Read-only comparison of batched and per-item demand retrieval on local data."""
from time import perf_counter
from unittest.mock import patch
import frappe
from frappe.utils import getdate, nowdate
from qcmc_logic import dynamic_reorder_service as service
from qcmc_logic.dynamic_reorder_demand import monthly_demand
from qcmc_logic.dynamic_reorder_calculation import demand_period

def run():
    if frappe.local.site!="erp.qcstyro.local" or frappe.session.user!="Administrator":
        frappe.throw("Local Administrator only")
    company="QC Styropackaging Corporation"
    as_of=getdate(nowdate())
    scopes=frappe.get_all("Item Reorder Override",filters={"company":company,"enabled":1},fields=["item_code","warehouse"])
    warehouses=sorted({r.warehouse for r in scopes})
    assert warehouses, "No enabled item overrides"
    results=[]
    def individual(company,warehouses,items,start,end,deduct_returns=True):
        data={}
        for item in items:
            data.update(monthly_demand(company,warehouses,[item],start,end,deduct_returns))
        return data
    for warehouse in warehouses:
        for method in ("Complete Calendar Months","Rolling Days","Month-to-Date Inclusive"):
            t=perf_counter()
            with patch.object(service,"monthly_demand",wraps=monthly_demand) as batch:
                actual=service.preview_rows(company,warehouse,as_of=as_of,period_method=method,rolling_days=90)
                calls=batch.call_count
            batch_seconds=perf_counter()-t
            t=perf_counter()
            with patch.object(service,"monthly_demand",side_effect=individual):
                expected=service.preview_rows(company,warehouse,as_of=as_of,period_method=method,rolling_days=90)
            single_seconds=perf_counter()-t
            assert sorted(actual,key=lambda r:r["item_code"])==sorted(expected,key=lambda r:r["item_code"]), (warehouse,method)
            results.append({"warehouse":warehouse,"method":method,"rows":len(actual),"batch_calls":calls,"batch_seconds":round(batch_seconds,3),"individual_seconds":round(single_seconds,3),"result":"PASS: identical recommendations"})
        # Compare raw demand over a larger item sample, even if not all items have policies.
        names=frappe.get_all("Item",filters={"disabled":0,"is_stock_item":1,"custom_inventory_group":"FG"},pluck="name",limit_page_length=100,order_by="name")
        if names:
            periods=demand_period(as_of,"Rolling Days",3,90)
            for deduct in (True,False):
                args=(company,[warehouse],names,periods[0][0],periods[-1][1],deduct)
                t=perf_counter()
                actual=monthly_demand(*args)
                batch_seconds=perf_counter()-t
                t=perf_counter()
                expected=individual(*args)
                single_seconds=perf_counter()-t
                assert actual==expected,(warehouse,deduct)
                results.append({"warehouse":warehouse,"items":len(names),"deduct_returns":deduct,"batch_seconds":round(batch_seconds,3),"individual_seconds":round(single_seconds,3),"result":"PASS: identical gross, returns and net demand"})
    return results
