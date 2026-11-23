"""Extend ERPNext Stock Entry native Connections with Storage Allocations.

The Stock Entry parent link is already stored on Storage Allocation. The
standard Frappe Connections machinery uses that link to filter correctly.
"""

def get_data(data):
    data.setdefault("non_standard_fieldnames", {})["Storage Allocation"] = "stock_entry"
    data.setdefault("internal_links", {})["Pick List"] = "pick_list"
    groups = data.setdefault("transactions", [])
    if not any("Pick List" in g.get("items", []) for g in groups):
        groups.append({"label": "Picking", "items": ["Pick List"]})
    if not any("Storage Allocation" in g.get("items", []) for g in groups):
        groups.append({"label": "Inventory", "items": ["Storage Allocation"]})
    return data
