import frappe
frappe.init(site='erp.qcstyro.local',sites_path='/home/qcmc_admin/frappe-bench/sites');frappe.connect()
try:
 print('territory',frappe.db.sql("SELECT name,parent_territory,is_group FROM `tabTerritory` WHERE name IN ('BATANGAS','BULACAN','SOUTH LUZON','NORTH LUZON')",as_dict=True))
 print('sales',frappe.db.sql("SELECT name,parent_sales_person,is_group FROM `tabSales Person` WHERE name IN ('BATANGAS','BULACAN','QC INSTITUTIONAL','SOUTH LUZON','NORTH LUZON') OR parent_sales_person IN ('BATANGAS','BULACAN') LIMIT 35",as_dict=True))
 print('customer territory counts',frappe.db.sql("SELECT territory,COUNT(*) n FROM `tabCustomer` GROUP BY territory ORDER BY n DESC LIMIT 12",as_dict=True))
 print('payments',frappe.db.sql("SELECT COUNT(*) FROM `tabPayment Entry`")[0][0])
finally:frappe.db.rollback();frappe.destroy()
