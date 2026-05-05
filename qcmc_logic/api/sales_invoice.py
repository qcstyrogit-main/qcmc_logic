import frappe

@frappe.whitelist()
def force_submit_sales_invoice(si_name):
    si = frappe.get_doc("Sales Invoice", si_name)

    if si.docstatus != 0:
        frappe.throw("Sales Invoice must be in Draft")

    # 🔴 STEP 1: backup delivery note references
    dn_map = {}
    for item in si.items:
        if item.delivery_note:
            dn_map[item.name] = {
                "delivery_note": item.delivery_note,
                "dn_detail": item.dn_detail
            }
            item.delivery_note = None
            item.dn_detail = None

    # 🔴 STEP 2: submit WITHOUT DN link
    si.flags.ignore_validate = True
    si.flags.ignore_links = True
    si.submit()


    si.set_status()
    # 🔴 STEP 3: restore DN links after submit
    for item in si.items:
        if item.name in dn_map:
            item.delivery_note = dn_map[item.name]["delivery_note"]
            item.dn_detail = dn_map[item.name]["dn_detail"]

    # si.save(ignore_permissions=True)
    si.flags.ignore_validate_update_after_submit = True

    for item in si.items:
        if item.name in dn_map:
            item.delivery_note = dn_map[item.name]["delivery_note"]
            item.dn_detail = dn_map[item.name]["dn_detail"]

    si.db_update()
    return si.name