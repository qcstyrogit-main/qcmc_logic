import frappe

def execute(filters=None):
    filters = filters or {}
    item_group = filters.get('item_group') or 'OS BB BOOKLET'
    warehouse = filters.get('warehouse') or 'Office Supplies - QC'

    columns = [
        {"label": "In Document", "fieldname": "in_document", "fieldtype": "Data", "width": 180},
        {"label": "In Doctype", "fieldname": "in_doctype", "fieldtype": "Data", "width": 120},
        {"label": "Item Code", "fieldname": "item_code", "fieldtype": "Link", "options": "Item", "width": 120},
        {"label": "Series From", "fieldname": "series_from", "fieldtype": "Int", "width": 110},
        {"label": "Series To", "fieldname": "series_to", "fieldtype": "Int", "width": 110},
        {"label": "Out Document", "fieldname": "out_document", "fieldtype": "Data", "width": 160},
        {"label": "Out Doctype", "fieldname": "out_doctype", "fieldtype": "Data", "width": 120},
        {"label": "Out Date", "fieldname": "out_date", "fieldtype": "Date", "width": 100},
        {"label": "Warehouse", "fieldname": "warehouse", "fieldtype": "Link", "options": "Warehouse", "width": 160} ,
        {"label": "Date Return", "fieldname": "date_return", "fieldtype": "Date", "width": 100 },
        {"label": "Note","fieldname": "note", "fieldtype": "Data", "width": 100},
        {"label": "Date Completed","fieldname": "date_completed", "fieldtype": "Date", "width": 100}
    ]

    # --- Incoming rows ---
    incoming_query = """
    SELECT sri.parent AS docname, 'Stock Reconciliation' AS doctype,
           sri.item_code, sri.qty, sri.custom_series_booklet_from
    FROM `tabStock Reconciliation Item` sri
    JOIN `tabItem` i ON i.item_code = sri.item_code
    WHERE i.item_group = %s AND sri.warehouse = %s
    UNION ALL
    SELECT pri.parent, 'Purchase Receipt', pri.item_code, pri.qty, pri.custom_series_booklet_from
    FROM `tabPurchase Receipt Item` pri
    JOIN `tabItem` i ON i.item_code = pri.item_code
    WHERE i.item_group = %s AND pri.warehouse = %s
    """
    incoming = frappe.db.sql(incoming_query, (item_group, warehouse, item_group, warehouse), as_dict=True)

    # --- Expand into series blocks ---
    series_rows = []
    for r in incoming:
        start = r.get('custom_series_booklet_from')
        qty = frappe.utils.cint(r.get('qty') or 0)
        if not start:
            continue
        try:
            start = int(start)
        except Exception:
            start = int(str(start).strip())

        for n in range(qty):
            series_rows.append({
                'in_document': r.get('docname'),
                'in_doctype': r.get('doctype'),
                'item_code': r.get('item_code'),
                'series_from': start + (n * 50),
                'series_to': start + (n * 50) + 49,
            })

    # --- Outgoing ---
    outgoing_query = """
    SELECT a.item_code, a.custom_series_booklet_from AS series_from,
           b.name AS out_document, b.stock_entry_type AS out_doctype,
           b.posting_date AS out_date, b.from_warehouse AS warehouse
    FROM `tabStock Entry Detail` a
    JOIN `tabStock Entry` b ON a.parent = b.name
    WHERE a.item_group = %s
      AND b.stock_entry_type IN ('Material Issue','Material Transfer')
      AND a.custom_series_booklet_from IS NOT NULL
    """
    outgoing = frappe.db.sql(outgoing_query, (item_group,), as_dict=True)

    outgoing_map = {}
    for o in outgoing:
        try:
            key = (o.get('item_code'), int(o.get('series_from')))
            outgoing_map[key] = o
        except Exception:
            continue
            
    # --- Return ---
    return_query = """
    SELECT parent as item_code, series_from, date_return, note, date_completed
    FROM `tabBooklet Monitoring Item`
    """
    return_rows = frappe.db.sql(return_query, as_dict=True)

    return_map = {}
    for rr in return_rows:
        try:
            key = (rr.get('item_code'), int(rr.get('series_from')))
            return_map[key] = rr
        except Exception:
            continue


    # --- Merge ---
    data = []
    for r in series_rows:
        key = (r['item_code'], int(r['series_from']))
        out = outgoing_map.get(key)
        ret = return_map.get(key)

        if out:
            r.update({
                'out_document': out.get('out_document'),
                'out_doctype': out.get('out_doctype'),
                'out_date': out.get('out_date'),
                'warehouse': out.get('warehouse'),
            })
        else:
            r.update({
                'out_document': None,
                'out_doctype': None,
                'out_date': None,
                'warehouse': None,
            })
        if ret:
            r.update({
                'date_return': ret.get('date_return'),
                'note': ret.get('note'),
                'date_completed': ret.get('date_completed'),
            })
        else:
            r.update({
                'date_return': None,
                'note': None,
                'date_completed': None,
            })
                      
        data.append(r)

    data = sorted(data, key=lambda x: (x.get('item_code') or '', x.get('series_from') or 0))

    return columns, data