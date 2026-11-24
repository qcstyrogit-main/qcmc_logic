import frappe

def run():
    dt="Purchase Invoice VAT Detail"
    specs={"account_name":(5,1),"cost_center":(3,1),"amount":(2,1)}
    changes=[]
    for field,(columns,in_list_view) in specs.items():
        custom=frappe.db.get_value("Custom Field",{"dt":dt,"fieldname":field},"name")
        if custom:
            doc=frappe.get_doc("Custom Field",custom)
        else:
            doc=frappe.get_doc("DocField",{"parent":dt,"fieldname":field})
        doc.columns=columns
        doc.in_list_view=in_list_view
        doc.save(ignore_permissions=True)
        changes.append({"field":field,"columns":columns})
    frappe.db.commit()
    frappe.clear_cache(doctype=dt)
    frappe.clear_cache(doctype="Purchase Invoice")
    return changes
