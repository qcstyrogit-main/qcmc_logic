import frappe
frappe.init(site="erp.qcstyro.local",sites_path="/home/qcmc_admin/frappe-bench/sites");frappe.connect()
try:
 for t in ("Sales Invoice","Payment Schedule"):
  print(t,[(x.fieldname,x.label,x.fieldtype) for x in frappe.get_meta(t).fields if "term" in (x.fieldname or "").lower() or "term" in (x.label or "").lower()])
 print("invoice_count",frappe.db.count("Sales Invoice"))
 print("invoice_sample",frappe.db.sql("SELECT name,payment_terms_template FROM `tabSales Invoice` ORDER BY modified DESC LIMIT 5",as_dict=True))
 print("schedule_sample",frappe.db.sql("SELECT parent,payment_term,description,credit_days FROM `tabPayment Schedule` WHERE parenttype='Sales Invoice' ORDER BY modified DESC LIMIT 5",as_dict=True))
finally:frappe.db.rollback();frappe.destroy()
