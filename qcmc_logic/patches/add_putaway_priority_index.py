import frappe


def execute():
    if frappe.db.table_exists("Putaway Rule"):
        frappe.db.add_index("Putaway Rule", ["warehouse", "company"], "qcmc_putaway_priority_scope")
