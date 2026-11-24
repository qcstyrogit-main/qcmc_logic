import frappe

def run():
    company="Multiplast Corporation"
    account="5212 - 5212 - Round Off - MC"
    existing=frappe.db.get_value("Company",company,"round_off_for_opening")
    if existing:
        return {"status":"already_configured","account":existing}
    a=frappe.db.get_value("Account",account,["company","is_group","disabled","account_type"],as_dict=True)
    if not a or a.company!=company or a.is_group or a.disabled or a.account_type!="Round Off":
        frappe.throw("Round-off account validation failed")
    frappe.db.set_value("Company",company,"round_off_for_opening",account)
    frappe.db.commit()
    return {"status":"configured","account":frappe.db.get_value("Company",company,"round_off_for_opening")}
