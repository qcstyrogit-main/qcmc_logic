from .accounts_payable_voucher_vat import execute
import frappe

def run():
    f={"company":"Multiplast Corporation","from_date":"2025-01-01","to_date":"2026-11-30"}
    columns,rows=execute(f)
    calculated=[r for r in rows if r.input_tax_eps is not None]
    return {"rows":len(rows),"calculated_rows":len(calculated),"examples":[{"pv_no":r.pv_no,"expense_account":r.expense_account,"base":r.pv_amount,"eps":r.input_tax_eps} for r in calculated[:5]]}
