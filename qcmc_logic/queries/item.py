import frappe

@frappe.whitelist()
def get_asset_items(doctype, txt, searchfield, start, page_len, filters):
    return frappe.db.sql("""
        SELECT name, item_name
        FROM `tabItem`
        WHERE
            (
                is_fixed_asset = 1
                OR (is_stock_item = 1 AND custom_is_asset_item = 1)
            )
            AND name NOT LIKE %(pattern1)s
            AND name NOT LIKE %(pattern2)s
            AND (name LIKE %(txt)s OR item_name LIKE %(txt)s)
        ORDER BY name
        LIMIT %(start)s, %(page_len)s
    """, {
        "pattern1": "DEP-%",
        "pattern2": "AMOR-%",
        "txt": f"%{txt}%",
        "start": start,
        "page_len": page_len
    })
