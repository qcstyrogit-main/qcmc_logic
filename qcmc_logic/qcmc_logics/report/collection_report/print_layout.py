from collections import OrderedDict
from datetime import datetime
from html import escape

from frappe.utils import flt, formatdate


def render_print(rows, filters):
    esc = lambda value: escape(str(value)) if value is not None else ""
    amount = lambda value: f"{flt(value):,.2f}" if value is not None else "—"
    date = lambda value: formatdate(value, "dd MMM yyyy") if value else "—"
    groups = OrderedDict()
    for row in rows:
        key = (row["salesman"], row["region"], row["area"])
        groups.setdefault(key, []).append(row)

    receipts = [r for r in rows if r["row_type"] == "receipt"]
    total_receipts = sum(flt(r.get("check_amount")) for r in receipts)
    total_ewt = sum(flt(r.get("ewt")) for r in receipts)
    total_unapplied = sum(flt(r.get("unapplied")) for r in receipts)
    total_allocated = sum(flt(r.get("paid_amount")) for r in rows if r["row_type"] == "allocation")

    css = """
    :root{--navy:#142a43;--ink:#172b44;--muted:#66788d;--line:#dce4ec;--soft:#f3f6fa;--blue:#2366a0}
    *{box-sizing:border-box}
    body{margin:0;background:#e9edf2;color:var(--ink);font:12px/1.5 Arial,Helvetica,sans-serif}
    .toolbar{position:sticky;top:0;z-index:10;background:white;border-bottom:1px solid var(--line);
      padding:12px 24px;display:flex;align-items:center;justify-content:space-between;gap:12px}
    .toolbar strong{font-size:13px}.toolbar small{color:var(--muted);display:block}
    button{background:var(--navy);border:0;border-radius:7px;color:white;padding:10px 16px;
      font-weight:700;cursor:pointer;font-size:12px}
    .sheet{max-width:1550px;margin:26px auto;padding:32px 34px;background:white;
      box-shadow:0 8px 32px #172b4415;border-radius:8px}
    .top{display:flex;justify-content:space-between;align-items:flex-start;border-bottom:2px solid var(--navy);padding-bottom:18px}
    .eyebrow{text-transform:uppercase;letter-spacing:1.8px;font-size:10px;font-weight:800;color:var(--blue)}
    h1{font-size:25px;letter-spacing:-.4px;margin:3px 0 5px;color:var(--navy)}
    .company{font-weight:700;font-size:14px}
    .period{font-size:12px;color:var(--muted);margin-top:6px}
    .meta{text-align:right;color:var(--muted);font-size:11px}
    .meta b{color:var(--ink)}
    .stats{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:20px 0 22px}
    .stat{border:1px solid var(--line);border-radius:7px;padding:12px 14px}
    .stat label{display:block;font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.7px}
    .stat strong{display:block;font-size:17px;margin-top:5px;font-variant-numeric:tabular-nums}
    .section{margin-top:20px;break-inside:avoid}
    .grouphead{background:var(--soft);padding:9px 12px;border-left:3px solid var(--blue);
      display:flex;justify-content:space-between;gap:12px;align-items:center}
    .grouphead strong{font-size:12px}.grouphead small{font-size:10px;color:var(--muted)}
    table{width:100%;border-collapse:collapse;table-layout:fixed;font-size:10px}
    th{text-align:left;background:#f8fafc;color:#536579;text-transform:uppercase;letter-spacing:.25px;
      font-size:9px;font-weight:800;border-bottom:1px solid var(--line);padding:9px 5px}
    td{border-bottom:1px solid #edf1f5;padding:7px 5px;vertical-align:top;overflow-wrap:anywhere}
    .num{text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}
    th.customer,td.customer{width:15%;text-align:left;white-space:normal;overflow-wrap:break-word}
    .receipt td{background:#fff;font-weight:650}
    .allocation td{color:#516276;background:#fafbfd}
    .allocation td:first-child{padding-left:12px}
    .muted{color:#8b98a8}.ref{font-weight:700;color:var(--ink)}
    .group-total td{background:#f3f6fa;font-weight:750;border-top:1px solid var(--line)}
    .footer{margin-top:24px;padding-top:12px;border-top:1px solid var(--line);font-size:10px;color:var(--muted)}
    .grand{margin-top:18px;background:var(--navy);color:white;padding:14px 16px;display:flex;justify-content:space-between;align-items:center}
    .grand strong{font-size:17px}
    .empty{text-align:center;padding:32px;color:var(--muted);border:1px dashed var(--line);margin-top:20px}
    @page{size:A4 landscape;margin:10mm}
    @media print{
      body{background:white;font-size:10px;-webkit-print-color-adjust:exact;print-color-adjust:exact}
      .toolbar{display:none!important}.sheet{max-width:none;margin:0;padding:0;box-shadow:none;border-radius:0}
      .top{padding-bottom:10px}h1{font-size:20px}.stats{margin:12px 0;gap:7px}
      .stat{padding:7px 9px}.stat strong{font-size:13px}
      .section{margin-top:12px}.grouphead{padding:6px 9px}
      table{font-size:8px}th{font-size:7px;padding:5px 3px}td{padding:4px 3px}
      thead{display:table-header-group}tr{break-inside:avoid}
      .grand{break-inside:avoid}
    }
    """
    html = ['<!doctype html><html lang="en"><head><meta charset="utf-8">',
            '<meta name="viewport" content="width=device-width, initial-scale=1">',
            '<title>Collection Report</title><style>', css, '</style></head><body>',
            '<div class="toolbar"><div><strong>Collection Report</strong><small>Print-ready accounting statement</small></div>',
            '<button onclick="window.print()">Print / Save as PDF</button></div>',
            '<main class="sheet"><header class="top"><div><div class="eyebrow">Accounts Receivable / Collections</div>',
            '<h1>Collection Report</h1><div class="company">', esc(filters.get("company")), '</div>',
            '<div class="period">', date(filters.get("from_date")), ' — ', date(filters.get("to_date")), '</div></div>',
            '<div class="meta"><b>QCMC · ERPNext</b><div>Grouped by Salesman / Region / Area</div>',
            '<div>Generated ', esc(datetime.now().strftime("%d %b %Y · %I:%M %p")), '</div></div></header>',
            '<div class="stats">']
    for label, value in [("Total Receipts", total_receipts), ("Invoice Allocations", total_allocated),
                         ("Creditable Withholding Tax", total_ewt), ("Unapplied Amount", total_unapplied)]:
        html.extend(['<div class="stat"><label>', esc(label), '</label><strong>', amount(value), '</strong></div>'])
    html.append('</div>')
    if not rows:
        html.append('<div class="empty"><strong>No collection records found.</strong><div>Try another company or reporting period.</div></div>')

    cols = [("OR No.", "or_no"), ("OR Date", "or_date"), ("Check No.", "check_no"),
            ("Check Date", "check_date"), ("Customer", "customer_name"), ("Check", "check_amount"), ("Unapplied", "unapplied"),
            ("Document No.", "doc_no"), ("Doc Date", "doc_date"), ("Doc Amt", "doc_amount"),
            ("EWT / CWT", "ewt"), ("Paid Amt", "paid_amount")]
    monetary = {"check_amount", "unapplied", "doc_amount", "ewt", "paid_amount"}
    dates = {"or_date", "check_date", "doc_date"}
    for (salesman, region, area), items in groups.items():
        group_receipts = [r for r in items if r["row_type"] == "receipt"]
        subtotal = sum(flt(r.get("check_amount")) for r in group_receipts)
        html.extend(['<section class="section"><div class="grouphead"><div><strong>',
                     esc(salesman), '</strong><small> &nbsp; · &nbsp; Region: ', esc(region),
                     ' &nbsp; · &nbsp; Area: ', esc(area), '</small></div><small>',
                     str(len(group_receipts)), ' receipts</small></div>',
                     '<table><thead><tr>'])
        for label, field in cols:
            html.extend(['<th', ' class="num"' if field in monetary else (' class="customer"' if field == "customer_name" else ''), '>', esc(label), '</th>'])
        html.append('</tr></thead><tbody>')
        for r in items:
            receipt = r["row_type"] == "receipt"
            html.append('<tr class="receipt">' if receipt else '<tr class="allocation">')
            for _, field in cols:
                value = r.get(field)
                if field in monetary:
                    displayed = amount(value) if value is not None and (flt(value) != 0 or field == "check_amount") else '—'
                elif field in dates:
                    displayed = date(value)
                else:
                    displayed = esc(value) if value else '—'
                # Invoice allocation rows are visually nested under their receipt.
                if not receipt and field in {"or_no", "or_date", "check_no", "check_date", "customer_name"}:
                    displayed = '—'
                html.extend(['<td', ' class="num"' if field in monetary else (' class="customer"' if field == "customer_name" else ''),
                             '>', displayed, '</td>'])
            html.append('</tr>')
        html.extend(['<tr class="group-total"><td colspan="5">Group total · ',
                     str(len(group_receipts)), ' receipts</td><td class="num">', amount(subtotal),
                     '</td><td colspan="6"></td></tr></tbody></table></section>'])
    html.extend(['<div class="grand"><span>TOTAL COLLECTIONS · RECEIPTS ONLY</span><strong>',
                 amount(total_receipts), '</strong></div>',
                 '<footer class="footer">EWT / CWT is sourced from recorded Creditable Withholding Tax deductions at receipt level. ',
                 'Invoice allocation rows are informational and must not be added to receipt totals. ',
                 'Area currently follows ERPNext Territory until a dedicated area mapping is configured.</footer>',
                 '</main></body></html>'])
    return ''.join(html)
