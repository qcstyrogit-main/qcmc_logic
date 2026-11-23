"""Add Warehouse Transfer to Pick List's native Connections tab.

Keep ERPNext's existing dashboard groups and link mappings intact.
"""
from frappe import _


def get_data(data):
    data.setdefault("non_standard_fieldnames", {})["Warehouse Transfer"] = "against_pick_list"
    groups = data.setdefault("transactions", [])
    if not any("Warehouse Transfer" in group.get("items", []) for group in groups):
        groups.append({"label": _("Inventory"), "items": ["Warehouse Transfer"]})
    return data
