from collections import OrderedDict
from datetime import datetime
from html import escape
from frappe.utils import flt, formatdate

def render_print(rows, filters):
    esc=lambda v:escape(str(v)) if v is not None else ""
    money=lambda v: f"{flt(v):,.2f}" if v is not None else "–"
    groups=OrderedDict()
    for r in rows:
        groups.setdefault(r.get("expense_account") or "UNASSIGNED EXPENSE ACCOUNT",[]).append(r)
    css="""@page{size:A4 landscape;margin:12mm 11mm}
    *{box-sizing:border-box}body{font:11px Arial,Helvetica,sans-serif;color:#17202a;background:#e8ebef;margin:0}
    .toolbar{padding:12px 22px;background:#fff;display:flex;justify-content:space-between;align-items:center;position:sticky;top:0;border-bottom:1px solid #d5dce4}
    button{background:#173c60;color:white;border:0;border-radius:5px;padding:10px 16px;cursor:pointer;font-weight:bold}
    .paper{background:white;max-width:1180px;margin:20px auto;padding:30px;box-shadow:0 3px 20px #0001}
    header{display:flex;justify-content:space-between;margin-bottom:16px}header strong{font-size:14px}
    .sub{margin-top:4px;font-size:12px;font-weight:bold}.meta{text-align:right;font-size:10px}
    table{border-collapse:collapse;width:100%;table-layout:fixed;font-size:10px}
    th{border-bottom:2px solid #444;padding:7px 4px;text-align:left}
    td{padding:4px;vertical-align:top;overflow-wrap:anywhere}
    .num{text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}
    .group td{font-weight:bold;padding-top:16px;border-bottom:1px solid #aaa}
    .subtotal td{font-weight:bold;border-top:1px solid #888;padding-top:7px;padding-bottom:12px}
    .grand td{font-weight:bold;border-top:2px solid #333;border-bottom:2px solid #333;padding:10px 4px}
    .notice{font-size:10px;margin-top:18px;color:#8a4b00}
    thead{display:table-header-group}tr{break-inside:avoid}
    @media print{body{background:#fff}.toolbar{display:none}.paper{max-width:none;margin:0;padding:0;box-shadow:none}header{margin-bottom:12px}}
    """
    h=['<!doctype html><html><head><meta charset="utf-8"><title>Accounts Payable Voucher - VAT</title><style>',css,
    '</style></head><body><div class="toolbar"><b>Accounts Payable Voucher - VAT</b><button onclick="window.print()">Print / Save as PDF</button></div>',
    '<main class="paper"><header><div><strong>',esc(filters.get("company")),'</strong><div>GENERAL LEDGER</div><div class="sub">ACCOUNTS PAYABLE VOUCHER - VAT</div></div>',
    '<div class="meta">Generated ',esc(datetime.now().strftime("%m/%d/%Y %I:%M %p")),'<div>Period: ',esc(filters.get("from_date")),' to ',esc(filters.get("to_date")),'</div></div></header>',
    '<table><colgroup><col style="width:25%"><col style="width:13%"><col style="width:12%"><col style="width:9%"><col style="width:11%"><col style="width:10%"><col style="width:10%"><col style="width:10%"></colgroup>',
    '<thead><tr><th>Supplier Name</th><th>Tin Number</th><th>PV NO.</th><th>PV Date</th><th class="num">PV Amt</th><th class="num">Input Tax-EPS</th><th class="num">Input Tax-PSP</th><th class="num">Input Tax-GEN</th></tr></thead><tbody>']
    totals=[0,0,0,0]
    for group,items in groups.items():
        h+=['<tr class="group"><td colspan="8">',esc(group),'</td></tr>']
        sums=[0,0,0,0]
        for r in items:
            vals=[r.get(k) for k in ("pv_amount","input_tax_eps","input_tax_psp","input_tax_gen")]
            for i,v in enumerate(vals):
                sums[i]+=flt(v);totals[i]+=flt(v)
            h+=['<tr><td>',esc(r.get("supplier_name")),'</td><td>',esc(r.get("tin_number")),'</td><td>',esc(r.get("pv_no")),'</td><td>',
                esc(formatdate(r.get("pv_date"),"MM/dd/yyyy") if r.get("pv_date") else ""),'</td>']
            for v in vals:h+=['<td class="num">',money(v),'</td>']
            h+=['</tr>']
        h+=['<tr class="subtotal"><td colspan="4" class="num">',esc(group),'</td>']
        for n in sums:h+=['<td class="num">',money(n),'</td>']
        h+=['</tr>']
    h+=['<tr class="grand"><td colspan="4" class="num">GRAND TOTAL</td>']
    for n in totals:h+=['<td class="num">',money(n),'</td>']
    h+=['</tr></tbody></table>']
    if not rows:h+=['<p>No submitted Purchase Invoices match the selected filters.</p>']
    h+=['<div class="notice">Input Tax-EPS / PSP / GEN show VAT Details amounts directly (already VAT). Classification follows company and Cost Center. All Cost Centers other than EPS or PSP/PLS are classified as GEN; missing amounts remain blank, not zero.</div></main></body></html>']
    return "".join(h)
