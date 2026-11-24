"""ERPNext APV VAT report. Legacy reference: APGL.dbo.TR_APV_VAT.
EPS/PSP/GEN classifications require a verified ERPNext mapping; do not infer them.
"""
import frappe
from frappe import _
from frappe.utils import getdate

def execute(filters=None):
    f=frappe._dict(filters or {})
    if not (f.get("company") and f.get("from_date") and f.get("to_date")):
        frappe.throw(_("Company and dates are required"))
    if getdate(f.from_date)>getdate(f.to_date):
        frappe.throw(_("Invalid date range"))
    if not frappe.has_permission("Purchase Invoice","read"):
        frappe.throw(_("Not permitted"),frappe.PermissionError)
    fields=[
      ("Expense Account","expense_account","Link","Account",250),
      ("Supplier Name","supplier_name","Data",None,220),
      ("TIN Number","tin_number","Data",None,145),
      ("PV NO.","pv_no","Link","Purchase Invoice",180),
      ("PV Date","pv_date","Date",None,105),
      ("PV Amt","pv_amount","Currency",None,125),
      ("Input Tax-EPS","input_tax_eps","Currency",None,130),
      ("Input Tax-PSP","input_tax_psp","Currency",None,130),
      ("Input Tax-GEN","input_tax_gen","Currency",None,130),
      ("Unclassified VAT","input_tax_unclassified","Currency",None,145)]
    columns=[dict(label=_(label),fieldname=field,fieldtype=kind,width=width,
                  **({"options":option} if option else {}))
             for label,field,kind,option,width in fields]
    conditions=["pi.company=%(company)s",
                "pi.posting_date BETWEEN %(from_date)s AND %(to_date)s",
                "pi.docstatus=1"]
    if f.get("supplier"):conditions.append("pi.supplier=%(supplier)s")
    if f.get("expense_account"):conditions.append("it.expense_account=%(expense_account)s")
    # PV Amt is from invoice item expense amounts. VAT Details is already tax.
    rows=frappe.db.sql("""
        SELECT pi.name pv_no,pi.posting_date pv_date,pi.supplier,pi.supplier_name,
               it.expense_account,SUM(it.base_net_amount) pv_amount,pi.company
        FROM `tabPurchase Invoice` pi
        JOIN `tabPurchase Invoice Item` it ON it.parent=pi.name
          AND it.parenttype='Purchase Invoice'
        WHERE """+" AND ".join(conditions)+"""
        GROUP BY pi.name,pi.posting_date,pi.supplier,pi.supplier_name,
                 it.expense_account,pi.company
        ORDER BY it.expense_account,pi.supplier_name,pi.posting_date,pi.name
    """,f,as_dict=True)
    allowed=set(frappe.get_list("Purchase Invoice",
      filters={"name":["in",list({r.pv_no for r in rows})]},
      pluck="name",limit_page_length=0)) if rows else set()
    rows=[r for r in rows if r.pv_no in allowed]
    tin_field=next((name for name in ("tax_id","tax_id_number")
       if frappe.db.has_column("Supplier",name)),None)
    suppliers=list({r.supplier for r in rows})
    tins=dict(frappe.db.sql("SELECT name,`"+tin_field+"` FROM `tabSupplier` WHERE name IN %(names)s",
      {"names":suppliers})) if tin_field and suppliers else {}
    invoice_names=list({r.pv_no for r in rows})
    vat_rows=frappe.db.sql("""
        SELECT v.parent pv_no,v.account_name expense_account,v.cost_center,
               v.amount,cc.company cost_center_company,cc.is_group
        FROM `tabPurchase Invoice VAT Detail` v
        LEFT JOIN `tabCost Center` cc ON cc.name=v.cost_center
        WHERE v.parent IN %(names)s AND v.parenttype='Purchase Invoice'
          AND v.parentfield='custom_vat_details'
    """,{"names":invoice_names},as_dict=True) if invoice_names else []
    from frappe.utils import flt
    allocated={}
    company_by_invoice={r.pv_no:r.company for r in rows}
    for v in vat_rows:
        invoice_company=company_by_invoice.get(v.pv_no)
        cc=(v.cost_center or "").upper()
        if not v.cost_center or v.cost_center_company != invoice_company or v.is_group:
            category="input_tax_unclassified"
        elif invoice_company not in ("Multiplast Corporation","QC Styropackaging Corporation"):
            category="input_tax_unclassified"
        elif "-EPS " in cc:
            category="input_tax_eps"
        elif "-PSP " in cc or "-PLS " in cc:
            category="input_tax_psp"
        else:
            # Preserve existing report behavior: valid other Cost Centers are GEN.
            # Verify the authoritative company mapping before changing this rule.
            category="input_tax_gen"
        key=(v.pv_no,v.expense_account,category)
        allocated[key]=allocated.get(key,0)+flt(v.amount)
    by_invoice={r.pv_no:r for r in rows}
    existing={(r.pv_no,r.expense_account) for r in rows}
    for (pv_no,account,category),amount in allocated.items():
        if (pv_no,account) not in existing and pv_no in by_invoice:
            base=by_invoice[pv_no]
            rows.append(frappe._dict(
                pv_no=pv_no,pv_date=base.pv_date,supplier=base.supplier,
                supplier_name=base.supplier_name,expense_account=account,
                pv_amount=None,company=base.company))
            existing.add((pv_no,account))
    for row in rows:
        row.tin_number=tins.get(row.supplier) or ""
        for category in ("input_tax_eps","input_tax_psp","input_tax_gen","input_tax_unclassified"):
            row[category]=allocated.get((row.pv_no,row.expense_account,category))
    rows.sort(key=lambda r:(r.expense_account or "",r.supplier_name or "",str(r.pv_date),r.pv_no))
    return columns, rows

@frappe.whitelist()
def print_report(company=None,from_date=None,to_date=None,supplier=None,expense_account=None):
    if not frappe.has_permission("Purchase Invoice","read"):
        frappe.throw(_("Not permitted"),frappe.PermissionError)
    filters=frappe._dict(company=company,from_date=from_date,to_date=to_date,
                        supplier=supplier,expense_account=expense_account)
    _,rows=execute(filters)
    from qcmc_logic.qcmc_logics.report.accounts_payable_voucher_vat.print_layout import render_print
    frappe.local.response["type"]="download"
    frappe.local.response["filename"]="Accounts_Payable_Voucher_VAT.html"
    frappe.local.response["content_type"]="text/html; charset=utf-8"
    frappe.local.response["display_content_as"]="inline"
    frappe.local.response["filecontent"]=render_print(rows,filters)

