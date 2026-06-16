import frappe


def execute():
    if not frappe.db.exists("DocType", "LMS Onboard"):
        return

    doc = frappe.get_doc("DocType", "LMS Onboard")
    doc.module = "LMS"
    doc.custom = 1
    doc.istable = 0
    doc.fields = []

    doc.append(
        "fields",
        {
            "fieldname": "user",
            "label": "User",
            "fieldtype": "Link",
            "options": "User",
            "in_list_view": 1,
        },
    )
    doc.append(
        "fields",
        {
            "fieldname": "lms_onboarding_done",
            "label": "LMS Onboarding Done",
            "fieldtype": "Check",
            "default": "0",
            "in_list_view": 1,
        },
    )
    doc.append(
        "fields",
        {
            "fieldname": "date_finished",
            "label": "Date Finished",
            "fieldtype": "Datetime",
        },
    )
    doc.append(
        "fields",
        {
            "fieldname": "amended_from",
            "label": "Amended From",
            "fieldtype": "Link",
            "options": "LMS Onboard",
            "no_copy": 1,
            "read_only": 1,
            "print_hide": 1,
        },
    )

    doc.save(ignore_permissions=True)
    frappe.clear_cache(doctype="LMS Onboard")
