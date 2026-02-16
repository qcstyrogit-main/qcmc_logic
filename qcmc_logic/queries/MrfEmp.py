import frappe

@frappe.whitelist()
def get_Employee(doctype, txt, searchfield, start, page_len, filters):
    conditions = []
    values = {
        "txt": f"%{txt}%",
        "start": start,
        "page_len": page_len,
    }

    # Optional filters
    if filters.get("company"):
        conditions.append("company = %(company)s")
        values["company"] = filters["company"]

    if filters.get("department"):
        conditions.append("department = %(department)s")
        values["department"] = filters["department"]

    if filters.get("designation"):
        conditions.append("(designation = %(designation)s or " \
        " name in (select employee from `tabEmployee Promotion` " \
        "where department = %(department)s AND company = %(company)s AND name in (select parent from `tabEmployee Property History` where fieldname = 'designation' and current = %(designation)s ))  )")
        values["designation"] = filters["designation"]

    condition_sql = ""
    if conditions:
        condition_sql = " AND " + " AND ".join(conditions)

    return frappe.db.sql(f"""
        SELECT name, employee_name
        FROM `tabEmployee`
        WHERE (name LIKE %(txt)s OR employee_name LIKE %(txt)s)
        {condition_sql}
        ORDER BY name
        LIMIT %(start)s, %(page_len)s
    """, values)
