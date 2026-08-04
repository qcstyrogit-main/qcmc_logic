import frappe


ROLE_PROFILE_ACCESS_LINKS = (
    ("Access", "Role Profile Warehouse Access", "role_profile"),
    ("Access", "Role Profile Inventory Group Access", "role_profile"),
    ("Access", "Role Profile Territory", "role_profile"),
)


def execute():
    if not frappe.db.exists("DocType", "Role Profile"):
        return

    role_profile = frappe.get_meta("Role Profile")
    existing_links = {
        (link.link_doctype, link.link_fieldname)
        for link in role_profile.get("links", [])
    }
    idx = len(role_profile.get("links", []))

    changed = False
    for group, link_doctype, link_fieldname in ROLE_PROFILE_ACCESS_LINKS:
        if not frappe.db.exists("DocType", link_doctype):
            continue

        key = (link_doctype, link_fieldname)
        if key in existing_links:
            continue

        idx += 1
        link = frappe.get_doc(
            {
                "doctype": "DocType Link",
                "group": group,
                "link_doctype": link_doctype,
                "link_fieldname": link_fieldname,
                "parent": "Role Profile",
                "parenttype": "DocType",
                "parentfield": "links",
                "idx": idx,
            },
        )
        link.db_insert()
        changed = True

    if changed:
        frappe.clear_cache(doctype="Role Profile")
