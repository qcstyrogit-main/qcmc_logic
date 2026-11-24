import frappe
def run():
 return frappe.get_all("Cost Center",fields=["name","cost_center_name","company","is_group"],filters={"company":["in",["Multiplast Corporation","QC Styropackaging Corporation"]]},limit_page_length=0)
