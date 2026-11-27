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
      ("Input Tax-GEN","input_tax_gen","Currency",None,130)]
    columns=[dict(label=_(label),fieldname=field,fieldtype=kind,width=width,
                  **({"options":option} if option else {}))
             for label,field,kind,option,width in fields]
    conditions=["pi.company=%(company)s",
                "pi.posting_date BETWEEN %(from_date)s AND %(to_date)s",
                "pi.docstatus=1"]
    if f.get("supplier"):conditions.append("pi.supplier=%(supplier)s")
    if f.get("expense_account"):conditions.append("v.account_name=%(expense_account)s")
    # VAT Details is the sole source of report amounts and expense accounts.
    rows=frappe.db.sql("""
        SELECT pi.name pv_no,pi.posting_date pv_date,pi.supplier,pi.supplier_name,
               v.account_name expense_account,pi.company
        FROM `tabPurchase Invoice` pi
        JOIN `tabPurchase Invoice VAT Detail` v ON v.parent=pi.name
          AND v.parenttype='Purchase Invoice' AND v.parentfield='custom_vat_details'
        WHERE """+" AND ".join(conditions)+"""
        GROUP BY pi.name,pi.posting_date,pi.supplier,pi.supplier_name,
                 v.account_name,pi.company
        ORDER BY v.account_name,pi.supplier_name,pi.posting_date,pi.name
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
    pv_amounts={}
    for v in vat_rows:
        cc=(v.cost_center or "").upper()
        if "-EPS " in cc:
            category="input_tax_eps"
        elif "-PSP " in cc or "-PLS " in cc:
            category="input_tax_psp"
        else:
            # Preserve existing report behavior: valid other Cost Centers are GEN.
            # Verify the authoritative company mapping before changing this rule.
            category="input_tax_gen"
        key=(v.pv_no,v.expense_account,category)
        from qcmc_logic.customs.apv_vat_validation import calculate_vat_detail
        vat_component, pv_component = calculate_vat_detail(v.amount)
        allocated[key]=allocated.get(key,0)+vat_component
        pv_key=(v.pv_no,v.expense_account)
        pv_amounts[pv_key]=pv_amounts.get(pv_key,0)+pv_component
    # One row per invoice and VAT Details expense account.
    for row in rows:
        row.pv_amount=pv_amounts.get((row.pv_no,row.expense_account))
        row.tin_number=tins.get(row.supplier) or ""
        for category in ("input_tax_eps","input_tax_psp","input_tax_gen"):
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

