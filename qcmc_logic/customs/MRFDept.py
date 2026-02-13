import frappe

@frappe.whitelist()
def get_departments_by_user(doctype, txt, searchfield, start, page_len, filters):

    # 🚫 No company = no departments
    if not filters or not filters.get("company"):
        return []

    # 👑 System Manager sees all departments for the company
    if "System Manager" in frappe.get_roles(frappe.session.user):
        return frappe.db.sql("""
            SELECT name, department_name
            FROM `tabDepartment`
            WHERE company = %(company)s
              AND (
                  name LIKE %(txt)s
                  OR department_name LIKE %(txt)s
              )
            ORDER BY name
            LIMIT %(start)s, %(page_len)s
        """, {
            "company": filters.get("company"),
            "txt": f"%{txt}%",
            "start": start,
            "page_len": page_len
        })

    # 🔒 Normal user — ONLY assigned departments
    return frappe.db.sql("""
        SELECT DISTINCT
            d.name,
            d.department_name
        FROM `tabDepartment` d
        INNER JOIN `tabStaffing Plan Assignment Details` spad
            ON spad.department = d.name
        INNER JOIN `tabStaffing Plan Assignment` spa
            ON spa.name = spad.parent
        WHERE spa.user = %(user)s
          AND d.company = %(company)s
          AND (
              d.name LIKE %(txt)s
              OR d.department_name LIKE %(txt)s
          )
        ORDER BY d.name
        LIMIT %(start)s, %(page_len)s
    """, {
        "user": frappe.session.user,
        "company": filters.get("company"),
        "txt": f"%{txt}%",
        "start": start,
        "page_len": page_len
    })


@frappe.whitelist()
def get_staffing_plans_by_department(doctype, txt, searchfield, start, page_len, filters):

    if not filters or not filters.get("department"):
        return []

    # 👑 System Manager sees all
    if "System Manager" in frappe.get_roles(frappe.session.user):
        return frappe.db.sql("""
        SELECT name
        FROM `tabStaffing Plan` 
        WHERE department = %(department)s
        AND name LIKE %(txt)s
        AND docstatus = 1
        ORDER BY name
        LIMIT %(start)s, %(page_len)s
    """, {
        "department": filters.get("department"),
        "txt": f"%{txt}%",
        "start": start,
        "page_len": page_len
    })
    
    
    return frappe.db.sql("""
        SELECT name
        FROM `tabStaffing Plan` 
        WHERE department = %(department)s
        AND name LIKE %(txt)s
        AND name in (SELECT staffing_plan from `tabStaffing Plan Assignment Details` where parent = %(user)s)
        ORDER BY name
        LIMIT %(start)s, %(page_len)s
    """, {
        "user": frappe.session.user,
        "department": filters.get("department"),
        "txt": f"%{txt}%",
        "start": start,
        "page_len": page_len
    })

