import frappe
def run():
 c="Multiplast Corporation"
 inv=frappe.db.get_value("Purchase Invoice","0426M00140-1",["name","is_opening","docstatus","rounding_adjustment","rounded_total","grand_total","company"],as_dict=True)
 accounts=frappe.get_all("Account",filters={"company":c,"root_type":["in",["Asset","Liability","Equity"]]},fields=["name","account_name","root_type","account_type","parent_account","is_group","disabled"],limit_page_length=0)
 candidates=[a for a in accounts if any(w in (a.account_name or "").lower() for w in ("round","opening","suspense","temporary","adjust"))]
 parents=[a for a in accounts if a.is_group and a.root_type in ("Asset","Liability","Equity") and (a.parent_account is None or any(w in (a.account_name or "").lower() for w in ("current","other","equity","liabilit")))]
 return {"invoice":inv,"candidates":candidates,"parents":parents[:55]}
