import frappe

@frappe.whitelist()
def get_booklet_items(doctype, txt, searchfield, start, page_len, filters):
    return frappe.db.sql("""
        SELECT name, item_name
        FROM `tabItem`
        WHERE
            item_group = %(itemgroup)s
            AND (name LIKE %(txt)s OR item_name LIKE %(txt)s)
            AND (name not in (SELECT name FROM `tabBooklet Monitoring`))
        ORDER BY name
        LIMIT %(start)s, %(page_len)s
    """, {
        "itemgroup": "OS BB BOOKLET",
        "txt": f"%{txt}%",
        "start": start,
        "page_len": page_len
    })


