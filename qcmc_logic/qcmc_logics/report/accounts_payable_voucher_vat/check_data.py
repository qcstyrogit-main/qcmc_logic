import frappe

def run():
    return frappe.db.sql("""
        SELECT company, COUNT(*) invoices, MIN(posting_date) first_date,
               MAX(posting_date) last_date
        FROM `tabPurchase Invoice` WHERE docstatus=1
        GROUP BY company ORDER BY invoices DESC LIMIT 12
    """,as_dict=True)
