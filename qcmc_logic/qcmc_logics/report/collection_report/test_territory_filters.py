import frappe
from qcmc_logic.qcmc_logics.report.collection_report.collection_report import territory_descendants,salesperson_query,execute
frappe.init(site='erp.qcstyro.local',sites_path='/home/qcmc_admin/frappe-bench/sites');frappe.connect();frappe.set_user('Administrator')
try:
 for territory in ['BATANGAS','NORTH LUZON','BULACAN','SOUTH LUZON']:
  children=territory_descendants(territory)
  sales=salesperson_query('Sales Person','','name',0,30,{'territory':territory})
  print(territory,'territories',len(children),'salespeople',sales[:10])
  assert sales,territory
  _,rows=execute({'company':'QC Styropackaging Corporation','from_date':'2026-01-01','to_date':'2026-11-30','territory':territory})
  print('report rows',len(rows))
 print('OK')
finally:frappe.db.rollback();frappe.destroy()
