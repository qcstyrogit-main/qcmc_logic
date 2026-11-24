import frappe
def run():
    result={}
    for dt in ("Purchase Invoice","Purchase Invoice Item","Purchase Invoice VAT Detail","Purchase Taxes and Charges","Account","Supplier"):
        if not frappe.db.exists("DocType",dt):continue
        meta=frappe.get_meta(dt)
        result[dt]=[{"field":f.fieldname,"label":f.label,"type":f.fieldtype,"options":f.options} for f in meta.fields if any(x in ((f.fieldname or "")+" "+(f.label or "")).lower() for x in ("e2","eps","psp","pls","vat","tax","opening","expense","account","amount","tin","classification"))][:75]
    result["vat_details_rows"]=frappe.db.sql("SELECT parent,account_name,amount FROM `tabPurchase Invoice VAT Detail` ORDER BY creation DESC LIMIT 8",as_dict=True) if frappe.db.table_exists("Purchase Invoice VAT Detail") else []
    result["tax_samples"]=frappe.db.sql("SELECT parent,account_head,description,rate,tax_amount,base_tax_amount FROM `tabPurchase Taxes and Charges` ORDER BY creation DESC LIMIT 8",as_dict=True)
    return result
