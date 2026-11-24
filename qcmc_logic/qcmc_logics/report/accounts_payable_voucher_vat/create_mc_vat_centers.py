import frappe

def run():
    company="Multiplast Corporation"
    parent="Multiplast Corporation - MC"
    if not frappe.db.exists("Cost Center",parent):
        frappe.throw("Multiplast root Cost Center not found")
    results=[]
    for label in ("VAT-EPS","VAT-PSP","VAT-GEN"):
        name=f"{label} - MC"
        existing=frappe.db.exists("Cost Center",{"company":company,"cost_center_name":label})
        if existing:
            results.append({"name":existing,"status":"existing"})
            continue
        doc=frappe.get_doc({"doctype":"Cost Center","cost_center_name":label,
            "company":company,"parent_cost_center":parent,"is_group":0})
        doc.insert(ignore_permissions=True)
        results.append({"name":doc.name,"status":"created"})
    frappe.db.commit()
    return results
