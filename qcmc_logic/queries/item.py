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
@frappe.whitelist()
def get_active_mr_states(doctype, txt, searchfield, start, page_len, filters):
    # Runs a lightning-fast SQL query to find only the workflow states actually being used
    states = frappe.db.sql("""
        SELECT DISTINCT workflow_state 
        FROM `tabMaterial Request` 
        WHERE workflow_state IS NOT NULL 
        AND workflow_state != ''
        AND workflow_state LIKE %(txt)s
    """, {'txt': f"%{txt}%"})
    
    return states

    