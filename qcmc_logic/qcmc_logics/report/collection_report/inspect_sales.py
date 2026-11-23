import frappe,json
frappe.init(site='erp.qcstyro.local',sites_path='/home/qcmc_admin/frappe-bench/sites');frappe.connect()
try:
 for t in ['Customer','Sales Team','Sales Person','Payment Entry','Sales Invoice']:
  fields=frappe.db.sql('SHOW COLUMNS FROM `tab'+t+'`',as_dict=True)
  print(t,[(f['Field'],f['Type']) for f in fields if any(k in f['Field'].lower() for k in ['sales','territory','area','customer','parent'])])
 print('sales people',frappe.db.sql('SELECT name,sales_person_name,enabled FROM `tabSales Person` LIMIT 8',as_dict=True))
 print('sales team sample',frappe.db.sql('SELECT parent,parenttype,sales_person,allocated_percentage FROM `tabSales Team` LIMIT 12',as_dict=True))
 print('customers count',frappe.db.sql('SELECT COUNT(*) FROM `tabCustomer`')[0][0])
 print('sales team count',frappe.db.sql('SELECT COUNT(*) FROM `tabSales Team`')[0][0])
finally:frappe.db.rollback();frappe.destroy()
