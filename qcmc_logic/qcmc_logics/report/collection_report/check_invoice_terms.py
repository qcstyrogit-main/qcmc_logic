import frappe
frappe.init(site="erp.qcstyro.local",sites_path="/home/qcmc_admin/frappe-bench/sites");frappe.connect()
try:
 names=['ACC-SINV-2026-01126','ACC-SINV-2026-01109','ACC-SINV-2026-00447','ACC-SINV-2026-01112']
 print(frappe.db.sql("SELECT name,payment_terms_template,due_date,posting_date FROM `tabSales Invoice` WHERE name IN %(names)s",{"names":names},as_dict=True))
 print(frappe.db.sql("SELECT parent,payment_term,credit_days,due_date FROM `tabPayment Schedule` WHERE parent IN %(names)s",{"names":names},as_dict=True))
finally:frappe.db.rollback();frappe.destroy()
