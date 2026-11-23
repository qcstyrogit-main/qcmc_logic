import frappe
frappe.init(site='erp.qcstyro.local',sites_path='/home/qcmc_admin/frappe-bench/sites');frappe.connect();frappe.set_user('Administrator')
try:
 print('user',frappe.session.user)
 print('count',frappe.db.sql("SELECT company,docstatus,payment_type,party_type,COUNT(*) n,MIN(posting_date) min_date,MAX(posting_date) max_date FROM `tabPayment Entry` GROUP BY company,docstatus,payment_type,party_type ORDER BY n DESC LIMIT 15",as_dict=True))
 print('list',frappe.get_list('Payment Entry',fields=['name'],limit_page_length=3))
except Exception as e:print(type(e).__name__,str(e))
finally:frappe.db.rollback();frappe.destroy()
