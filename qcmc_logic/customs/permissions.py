import frappe

def appraisal_permission_query(user):
    roles = frappe.get_roles(user)

    # Only restrict supervisors, never managers/admins
    if "Appraisal User" not in roles or "Appraisal Manager" in roles:
        return ""

    assignment = frappe.db.get_value(
        "Appraisal Section Assignment",
        {"user": user},
        "name"
    )

    if not assignment:
        return "1=0"

    sections = frappe.get_all(
        "Appraisal Section Assignment Detail",
        filters={"parent": assignment},
        pluck="appraisal_section"
    )

    if not sections:
        return "1=0"

    sections_sql = ", ".join(frappe.db.escape(s) for s in sections)

    return f"`tabAppraisal`.custom_appraisal_section IN ({sections_sql})"