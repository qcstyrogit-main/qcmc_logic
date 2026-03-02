import frappe
from frappe import _

@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def get_staffing_plan_edsa(doctype, txt, searchfield, start, page_len, filters):

    return frappe.db.sql("""
        SELECT name
        FROM `tabStaffing Plan`
        WHERE docstatus = 1
        AND ({key} LIKE %(txt)s)
        ORDER BY name
        LIMIT %(start)s, %(page_len)s
    """.format(key=searchfield), {
        "txt": f"%{txt}%",
        "start": start,
        "page_len": page_len
    })