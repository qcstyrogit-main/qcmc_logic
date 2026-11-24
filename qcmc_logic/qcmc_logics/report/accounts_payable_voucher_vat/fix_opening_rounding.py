import frappe

def run():
    company="Multiplast Corporation"
    account="203 - TEMPORARY OPENING - MC"
    existing=frappe.db.get_value("Company",company,"round_off_for_opening")
    a=frappe.db.get_value("Account",account,["company","root_type","is_group","disabled","account_type"],as_dict=True)
    if not a or a.company!=company or a.root_type not in ("Asset","Liability","Equity") or a.is_group or a.disabled:
        frappe.throw("Opening account is not a valid active balance sheet ledger")
    if existing!=account:
        frappe.db.set_value("Company",company,"round_off_for_opening",account)
        frappe.db.commit()
    return {"status":"configured","opening_round_off":frappe.db.get_value("Company",company,"round_off_for_opening"),"regular_round_off":frappe.db.get_value("Company",company,"round_off_account")}
