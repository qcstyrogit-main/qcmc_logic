import frappe

def run():
    ps_name = "Machine Shop Job Request-amended_from-hidden"
    if frappe.db.exists("Property Setter", ps_name):
        frappe.delete_doc("Property Setter", ps_name, ignore_permissions=True, force=True)
        frappe.db.commit()
        frappe.clear_cache(doctype="Machine Shop Job Request")
        print("Property Setter deleted — References section restored.")
    else:
        print("Not found — nothing to revert.")
