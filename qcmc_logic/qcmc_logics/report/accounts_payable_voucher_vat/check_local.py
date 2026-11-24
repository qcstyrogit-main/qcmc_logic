import frappe
from .accounts_payable_voucher_vat import execute

def run():
    company="QC Styropackaging Corporation"
    columns, rows=execute({"company":company,"from_date":"2026-03-01","to_date":"2026-03-31"})
    from .print_layout import render_print
    html=render_print(rows,{"company":company,"from_date":"2026-03-01","to_date":"2026-03-31"})
    return {"company":company,"columns":len(columns),"rows":len(rows),"print_html_chars":len(html),"has_grand_total":"GRAND TOTAL" in html}
