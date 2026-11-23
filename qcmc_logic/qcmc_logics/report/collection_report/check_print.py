import frappe,traceback
from qcmc_logic.qcmc_logics.report.collection_report.collection_report import print_report
frappe.init(site='erp.qcstyro.local',sites_path='/home/qcmc_admin/frappe-bench/sites')
frappe.connect()
frappe.set_user('Administrator')
try:
 print_report(company='QC Styropackaging Corporation',from_date='2026-10-01',to_date='2026-10-31')
 print('PRINT_OK',frappe.local.response.get('type'))
except Exception:
 traceback.print_exc()
finally:
 frappe.db.rollback()
 frappe.destroy()
