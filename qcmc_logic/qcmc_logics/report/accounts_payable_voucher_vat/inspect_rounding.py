import frappe
def run():
    company="Multiplast Corporation"
    fields=[f.fieldname for f in frappe.get_meta("Company").fields if "round" in f.fieldname.lower() and f.fieldtype not in ("Section Break","Column Break","HTML","Tab Break") and frappe.db.has_column("Company",f.fieldname)]
    settings=frappe.db.get_value("Company",company,fields,as_dict=True) if fields else {}
    accounts=frappe.get_all("Account",filters={"company":company},fields=["name","account_name","root_type","account_type","parent_account","is_group","disabled"],limit_page_length=0)
    matches=[a for a in accounts if any(k in (a.account_name or "").lower() for k in ("round","adjust","miscellaneous"))]
    parents=[a for a in accounts if a.is_group and a.root_type in ("Expense","Income") and ("indirect" in a.account_name.lower() or "other" in a.account_name.lower() or "expense" in a.account_name.lower())]
    return {"fields":fields,"settings":settings,"matches":matches,"parents":parents[:35]}
