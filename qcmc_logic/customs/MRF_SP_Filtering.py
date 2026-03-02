import frappe
from frappe.utils import cint

@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def staffing_plan_link_query(doctype, txt, searchfield, start, page_len, filters):
    filters = filters or {}
    user = frappe.session.user  # current logged in user
    user_roles = frappe.get_roles(user)
    exception_roles = ['System Manager','HR User']
    has_exception_roles = any(role in exception_roles for role in user_roles)


    # Your assumption: Staffing Plan Assignment.name == user (email)
    user_parent = frappe.db.escape(user)

    where = ["sp.docstatus = 1", "sp.name LIKE %(txt)s"]
    params = {"txt": f"%{txt}%", "start": cint(start), "page_len": cint(page_len)}

    # Assigned-to-user filter via child table parent
    where.append(f"""
        sp.name IN (
            SELECT spd.staffing_plan
            FROM `tabStaffing Plan Assignment Details` spd
            WHERE spd.parent = {user_parent}
        )
    """)
    if has_exception_roles:
        return frappe.db.sql(
        f"""
        SELECT sp.name, sp.name
        FROM `tabStaffing Plan` sp
        where sp.docstatus = 1
        and sp.name LIKE %(txt)s
        ORDER BY sp.name
        LIMIT %(page_len)s OFFSET %(start)s
        """,
        params
    )
    
    # Apply your existing logic
    return frappe.db.sql(
        f"""
        SELECT sp.name, sp.name
        FROM `tabStaffing Plan` sp
        WHERE {" AND ".join(where)}
        ORDER BY sp.name
        LIMIT %(page_len)s OFFSET %(start)s
        """,
        params
    )