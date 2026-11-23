import frappe
frappe.init(site='erp.qcstyro.local',sites_path='/home/qcmc_admin/frappe-bench/sites')
frappe.connect()
print('REPORT_EXISTS',frappe.db.exists('Report','Collection Report'))
print('PAYMENTS',frappe.db.count('Payment Entry'))
frappe.destroy()
