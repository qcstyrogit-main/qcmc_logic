"""Read-only candidate filtering equivalence and timing checks."""
from time import perf_counter
from unittest.mock import patch
import frappe
from frappe.utils import getdate, nowdate
from qcmc_logic import dynamic_reorder_service as service

def run():
    if frappe.local.site!="erp.qcstyro.local" or frappe.session.user!="Administrator":
        frappe.throw("Local Administrator only")
    company="QC Styropackaging Corporation"
    as_of=getdate(nowdate())
    scopes=frappe.get_all("Item Reorder Override",filters={"company":company,"enabled":1},fields=["item_code","warehouse"])
    warehouses=sorted({r.warehouse for r in scopes})
    assert warehouses
    output=[]
    for warehouse in warehouses:
        args=dict(company=company,warehouse=warehouse,as_of=as_of,period_method="Rolling Days",rolling_days=90)
        start=perf_counter()
        optimized=service.preview_rows(**args)
        optimized_seconds=perf_counter()-start
        start=perf_counter()
        with patch.object(service,"candidate_scope",return_value=None):
            baseline=service.preview_rows(**args)
        baseline_seconds=perf_counter()-start
        assert sorted(optimized,key=lambda r:r["item_code"])==sorted(baseline,key=lambda r:r["item_code"]), warehouse
        output.append(dict(warehouse=warehouse,rows=len(optimized),optimized_seconds=round(optimized_seconds,3),baseline_seconds=round(baseline_seconds,3),result="PASS: identical recommendations"))
        for row in optimized:
            assert service.preview_rows(**args,item_code=row["item_code"])==[row], row["item_code"]
        output.append(dict(warehouse=warehouse,result="PASS: explicit item filter matches warehouse preview"))
    return output
