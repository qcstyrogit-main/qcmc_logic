from pathlib import Path
root=Path('/home/qcmc_admin/frappe-bench/apps/qcmc_logic/qcmc_logic/qcmc_logics/report/collection_report')
p=root/'collection_report.py'
s=p.read_text()
s=s.replace('("territory","c.territory"),("sales_manager","c.custom_sales_manager")','("territory","c.territory")')
needle='    cwt={d.parent:flt(d.amount) for d in deductions}'
replacement='''    # Salesperson assignment is normally stored on Sales Invoice > Sales Team,
    # not on the Customer custom_sales_manager field.
    invoice_names=list({r.reference_name for r in refs if r.reference_doctype=="Sales Invoice"})
    invoice_sales={}
    if invoice_names:
        teams=frappe.db.sql("""
            SELECT parent,sales_person,allocated_percentage,idx
            FROM `tabSales Team`
            WHERE parenttype='Sales Invoice' AND parent IN %(invoices)s
            ORDER BY parent,allocated_percentage DESC,idx
        """,{"invoices":invoice_names},as_dict=True)
        for t in teams:
            invoice_sales.setdefault(t.parent,[]).append(t.sales_person)
    cwt={d.parent:flt(d.amount) for d in deductions}'''
assert needle in s
s=s.replace(needle,replacement)
needle='''    out=[]
    for p in payments:
        cancelled=p.docstatus==2'''
replacement='''    out=[]
    for p in payments:
        assigned=[]
        for r in by_parent.get(p.name,[]):
            assigned.extend(invoice_sales.get(r.reference_name,[]))
        assigned=list(dict.fromkeys(assigned))
        salesperson=", ".join(assigned) if assigned else (p.custom_sales_manager or "UNASSIGNED")
        selected=f.get("sales_manager")
        if selected and selected not in assigned and selected!=p.custom_sales_manager:
            continue
        cancelled=p.docstatus==2'''
assert needle in s
s=s.replace(needle,replacement)
s=s.replace('salesman=p.custom_sales_manager or "UNASSIGNED"','salesman=salesperson')
p.write_text(s)
j=root/'collection_report.js'
t=j.read_text()
old='{fieldname:"sales_manager",label:__("Sales Manager"),fieldtype:"Data"}'
new='{fieldname:"sales_manager",label:__("Salesperson"),fieldtype:"Link",options:"Sales Person"}'
assert old in t
j.write_text(t.replace(old,new))
print('UPDATED salesperson mapping and filter')
