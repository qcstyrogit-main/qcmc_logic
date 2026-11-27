"""Local read-only SQL smoke/equivalence check; no documents, commits or requests."""
import frappe
from qcmc_logic.dynamic_reorder_clock import business_date
from qcmc_logic.dynamic_reorder_calculation import demand_period
from qcmc_logic.dynamic_reorder_demand import monthly_demand, DEMAND_SOURCES


def run():
    if frappe.local.site!="erp.qcstyro.local" or frappe.session.user!="Administrator":
        frappe.throw("Local Administrator only")
    mapping=frappe.get_all("Reorder Policy Mapping",fields=["company","warehouse"],limit_page_length=1)[0]
    warehouses=frappe.get_all("Warehouse",filters={"company":mapping.company,"disabled":0,"is_group":0},pluck="name",order_by="name",limit_page_length=2)
    if mapping.warehouse and mapping.warehouse not in warehouses:
        warehouses=[mapping.warehouse]+warehouses[:1]
    periods=demand_period(business_date(),"Rolling Days",rolling_days=90)
    posted=frappe.db.sql("""SELECT DISTINCT s.item_code FROM `tabStock Ledger Entry` s
        JOIN `tabDelivery Note` dn ON dn.name=s.voucher_no
        WHERE s.company=%s AND s.warehouse IN %s AND s.voucher_type='Delivery Note'
          AND s.posting_date BETWEEN %s AND %s AND s.is_cancelled=0 AND dn.docstatus=1
          AND s.actual_qty<0 LIMIT 3""",(mapping.company,tuple(warehouses),periods[0][0],periods[-1][1]))
    items=[row[0] for row in posted] or frappe.get_all("Item",filters={"disabled":0,"is_stock_item":1,"has_variants":0},pluck="name",order_by="name",limit_page_length=3)
    assert warehouses and items
    args=(mapping.company,warehouses,items,periods[0][0],periods[-1][1])
    batched=monthly_demand(*args)
    individual={}
    for item in items:
        individual.update(monthly_demand(mapping.company,warehouses,[item],periods[0][0],periods[-1][1]))
    assert batched==individual,"Batched and individual demand differ"
    parts=[monthly_demand(*args,sources=[source]) for source in DEMAND_SOURCES]
    for key in set(batched).union(*(set(part) for part in parts)):
        for field in ("gross","returns","net"):
            assert batched.get(key,{}).get(field,0)==sum(part.get(key,{}).get(field,0) for part in parts)
    return dict(status="PASS",checks=["All four production SQL sources execute on local MariaDB",
        "Batched demand equals per-item demand","Source subtotals equal consolidated totals"],
        sampled_items=len(items),sampled_warehouses=len(warehouses),monthly_rows=len(batched),writes=0)
