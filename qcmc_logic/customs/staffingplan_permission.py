# staffingplan_permission.py
import frappe

def mrf_permission_query_condition(user):
    user_roles = frappe.get_roles(user)
    exception_roles = ['System Manager','HR User']
    has_exception_roles = any(role in exception_roles for role in user_roles)

    if has_exception_roles:
        return ""

    user = frappe.db.escape(user)

    return f"""
        `tabJob Requisition`.custom_staffing_plan IN (
            SELECT spc.staffing_plan
            FROM `tabStaffing Plan Assignment` spa
            INNER JOIN `tabStaffing Plan Assignment Details` spc
                ON spc.parent = spa.name
                AND spc.parenttype = 'Staffing Plan Assignment'
            WHERE spa.user = {user}
        )
    """
