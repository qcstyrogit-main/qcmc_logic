import frappe
from qcmc_logic.qcmc_logics.report.collection_report.collection_report import execute
frappe.init(site='erp.qcstyro.local',sites_path='/home/qcmc_admin/frappe-bench/sites');frappe.connect();frappe.set_user('Administrator')
try:
 for company in ['QC Styropackaging Corporation','Multiplast Corporation']:
  columns,rows=execute({'company':company,'from_date':'2026-01-01','to_date':'2026-11-30'})
  names=sorted(set(r['salesman'] for r in rows if r['salesman']!='UNASSIGNED'))
  print(company,'rows',len(rows),'assigned',len(names),'samples',names[:12])
  if names:
   _,filtered=execute({'company':company,'from_date':'2026-01-01','to_date':'2026-11-30','sales_manager':names[0]})
   print('FILTER',names[0],len(filtered))
finally:frappe.db.rollback();frappe.destroy()
