import frappe

def run():
    ps_name = "Machine Shop Job Request-amended_from-hidden"
    if frappe.db.exists("Property Setter", ps_name):
        print("Already exists.")
        return
    frappe.get_doc({
        "doctype": "Property Setter",
        "doctype_or_field": "DocField",
        "doc_type": "Machine Shop Job Request",
        "field_name": "amended_from",
        "property": "hidden",
        "property_type": "Check",
        "value": "1",
    }).insert(ignore_permissions=True)
    frappe.db.commit()
    frappe.clear_cache(doctype="Machine Shop Job Request")
    print("Done — References section hidden.")
