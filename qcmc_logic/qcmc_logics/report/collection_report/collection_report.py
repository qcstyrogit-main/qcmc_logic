import frappe
from frappe import _
from frappe.utils import flt, getdate

FIELDS = [
("Salesman","salesman","Data",170),("Region","region","Data",110),("Area","area","Data",110),
("OR NO.","or_no","Link",170),("OR Date","or_date","Date",100),("Check NO.","check_no","Data",140),
("Check Date","check_date","Date",105),("Customer","customer_name","Data",200),("Payment Terms","payment_terms","Data",140),
("Check","check_amount","Currency",120),("Unapply","unapplied","Currency",120),
("Doc NO.","doc_no","Data",130),("Doc Date","doc_date","Date",100),
("Doc Amt","doc_amount","Currency",120),("EWT (CWT)","ewt","Currency",115),
("Paid Amt","paid_amount","Currency",120),("Status","status","Data",90)
]

def territory_descendants(territory):
    """Include leaf territories when a regional parent is selected."""
    bounds = frappe.db.get_value("Territory", territory, ["lft", "rgt"], as_dict=True)
    if not bounds:
        return [territory]
    return frappe.get_all("Territory",
        filters={"lft": [">=", bounds.lft], "rgt": ["<=", bounds.rgt]},
        pluck="name", limit_page_length=0) or [territory]


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def salesperson_query(doctype, txt, searchfield, start, page_len, filters):
    """Link search restricted to Sales Person nodes under the selected Territory."""
    if not frappe.has_permission("Sales Person", "read"):
        return []
    territory = (filters or {}).get("territory")
    conditions = ["sp.enabled=1", "sp.is_group=0"]
    params = {"txt": "%" + (txt or "") + "%", "start": int(start), "page_len": int(page_len)}
    if territory:
        # Both hierarchies use matching region/territory names in this installation.
        names = territory_descendants(territory)
        names.append(territory)
        # Select sales people whose name or parent is in the chosen territory subtree.
        # This includes leaf salespeople under a selected parent region.
        conditions.append("(sp.name IN %(names)s OR sp.parent_sales_person IN %(names)s)")
        params["names"] = tuple(set(names))
    conditions.append("(sp.name LIKE %(txt)s OR sp.sales_person_name LIKE %(txt)s)")
    return frappe.db.sql("""
        SELECT sp.name, sp.parent_sales_person FROM `tabSales Person` sp
        WHERE """ + " AND ".join(conditions) + """
        ORDER BY sp.name LIMIT %(start)s, %(page_len)s
    """, params)


def get_rows(filters):
    f = frappe._dict(filters or {})
    if not f.get("company") or not f.get("from_date") or not f.get("to_date"):
        frappe.throw(_("Company and date range required"))
    if getdate(f.from_date)>getdate(f.to_date):
        frappe.throw(_("Invalid date range"))
    cond=["p.company=%(company)s","p.posting_date BETWEEN %(from_date)s AND %(to_date)s",
          "p.payment_type='Receive'","p.party_type='Customer'",
          "p.docstatus IN (1,2)" if int(f.get("include_cancelled") or 0) else "p.docstatus=1"]
    for k,c in [("customer","p.party"),("customer_group","c.customer_group")]:
        if f.get(k):cond.append(c+"=%("+k+")s")
    if f.get("territory"):
        territories = territory_descendants(f.territory)
        cond.append("c.territory IN %(territories)s")
        f.territories = tuple(territories)
    payments=frappe.db.sql("""
    SELECT p.name,p.company,p.posting_date,p.reference_no,p.reference_date,
    p.base_received_amount,p.base_total_allocated_amount,p.docstatus,p.party,p.party_name,
    c.customer_name,c.territory,c.custom_sales_manager
    FROM `tabPayment Entry` p LEFT JOIN `tabCustomer` c ON c.name=p.party
    WHERE """+" AND ".join(cond)+""" ORDER BY c.custom_sales_manager,c.territory,p.posting_date,p.name
    """,f,as_dict=True)
    if not payments:return []
    # Enforce per-document permissions, not just report role permissions.
    permitted=set(frappe.get_list("Payment Entry",filters={"name":["in",[p.name for p in payments]]},
                                  pluck="name",limit_page_length=0))
    payments=[p for p in payments if p.name in permitted]
    if not payments:return []
    names=[p.name for p in payments]
    refs=frappe.db.sql("""
    SELECT r.parent,r.reference_doctype,r.reference_name,r.allocated_amount,
    s.posting_date AS doc_date,s.base_grand_total AS doc_amount,
    COALESCE(NULLIF(TRIM(r.payment_term), ''),
      NULLIF(TRIM(s.payment_terms_template), ''),
      (SELECT NULLIF(TRIM(ps.payment_term), '') FROM `tabPayment Schedule` ps
       WHERE ps.parent=s.name AND ps.parenttype='Sales Invoice'
         AND ps.payment_term IS NOT NULL AND ps.payment_term <> ''
       ORDER BY ps.idx LIMIT 1)) AS payment_terms
    FROM `tabPayment Entry Reference` r
    LEFT JOIN `tabSales Invoice` s ON r.reference_doctype='Sales Invoice' AND s.name=r.reference_name
    WHERE r.parent IN %(names)s AND r.parenttype='Payment Entry' AND r.allocated_amount<>0
    ORDER BY r.parent,r.idx
    """,{"names":names},as_dict=True)
    deductions=frappe.db.sql("""
    SELECT d.parent,SUM(d.amount) amount FROM `tabPayment Entry Deduction` d
    WHERE d.parent IN %(names)s AND UPPER(d.account) LIKE '%%CREDITABLE WITHHOLDING TAX%%'
    GROUP BY d.parent
    """,{"names":names},as_dict=True)
    # Salesperson assignment is normally stored on Sales Invoice > Sales Team,
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
    cwt={d.parent:flt(d.amount) for d in deductions}
    by_parent={}
    for r in refs:by_parent.setdefault(r.parent,[]).append(r)
    out=[]
    for p in payments:
        assigned=[]
        for r in by_parent.get(p.name,[]):
            assigned.extend(invoice_sales.get(r.reference_name,[]))
        assigned=list(dict.fromkeys(assigned))
        salesperson=", ".join(assigned) if assigned else (p.custom_sales_manager or "UNASSIGNED")
        selected=f.get("sales_manager")
        if selected and selected not in assigned and selected!=p.custom_sales_manager:
            continue
        cancelled=p.docstatus==2
        # Display invoice payment terms on the receipt row as well as the
        # allocation row. A receipt can settle invoices with different terms.
        invoice_terms = list(dict.fromkeys(
            str(r.payment_terms).strip() for r in by_parent.get(p.name, [])
            if r.payment_terms and str(r.payment_terms).strip()
        ))
        receipt_terms = ", ".join(invoice_terms) if invoice_terms else None
        base=dict(salesman=salesperson,region=p.territory or "UNASSIGNED",
                  area=p.territory or "UNASSIGNED",or_no=p.name,or_date=p.posting_date,
                  check_no=p.reference_no,check_date=p.reference_date,
                  customer_name=p.customer_name or p.party_name,status="Cancelled" if cancelled else "Submitted",
                  payment_terms=receipt_terms)
        out.append(dict(base,check_amount=0 if cancelled else flt(p.base_received_amount),
            unapplied=0 if cancelled else max(0,flt(p.base_received_amount)-flt(p.base_total_allocated_amount)),
            doc_no=None,doc_date=None,doc_amount=None,ewt=0 if cancelled else cwt.get(p.name,0),
            paid_amount=None,row_type="receipt"))
        if not cancelled:
            for r in by_parent.get(p.name,[]):
                out.append(dict(base,check_amount=None,unapplied=None,doc_no=r.reference_name,
                                doc_date=r.doc_date,doc_amount=r.doc_amount,ewt=None,
                                payment_terms=r.payment_terms,
                                paid_amount=flt(r.allocated_amount),row_type="allocation"))
    return out

def execute(filters=None):
    cols=[{"label":_(label),"fieldname":field,"fieldtype":ft,"width":width}
          for label,field,ft,width in FIELDS]
    # Link to Payment Entry for OR NO.
    next(c for c in cols if c["fieldname"]=="or_no")["options"]="Payment Entry"
    return cols,get_rows(filters)

@frappe.whitelist()
def print_report(company=None,from_date=None,to_date=None,sales_manager=None,territory=None,
                 customer=None,customer_group=None,include_cancelled=0):
    if not frappe.has_permission("Payment Entry","read"):
        frappe.throw(_("Not permitted"),frappe.PermissionError)
    filters=frappe._dict(locals())
    rows=get_rows(filters)
    from qcmc_logic.qcmc_logics.report.collection_report.print_layout import render_print
    frappe.local.response["type"] = "download"
    frappe.local.response["filename"] = "Collection_Report.html"
    frappe.local.response["content_type"] = "text/html; charset=utf-8"
    frappe.local.response["display_content_as"] = "inline"
    frappe.local.response["filecontent"] = render_print(rows, filters)
    return
