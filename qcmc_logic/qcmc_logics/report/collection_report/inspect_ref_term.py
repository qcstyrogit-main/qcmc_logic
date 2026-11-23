import frappe
frappe.init(site='erp.qcstyro.local',sites_path='/home/qcmc_admin/frappe-bench/sites');frappe.connect()
try:
 print([(x.fieldname,x.label,x.fieldtype) for x in frappe.get_meta('Payment Entry Reference').fields if 'term' in (x.fieldname or '').lower()])
 print(frappe.db.sql("SHOW COLUMNS FROM `tabPayment Entry Reference` LIKE 'payment_term'",as_dict=True))
finally:frappe.db.rollback();frappe.destroy()
