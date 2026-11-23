import frappe
from qcmc_logic.qcmc_logics.report.collection_report.collection_report import execute
frappe.init(site='erp.qcstyro.local',sites_path='/home/qcmc_admin/frappe-bench/sites')
frappe.connect()
frappe.set_user('Administrator')
try:
    columns, rows = execute({'company':'QC Styropackaging Corporation','from_date':'2026-10-01','to_date':'2026-10-31'})
    print('EXECUTE_OK',len(columns),len(rows))
finally:
    frappe.db.rollback()
    frappe.destroy()
