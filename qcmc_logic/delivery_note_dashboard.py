"""Expose Delivery Note item Pick List references in native Connections.

Use the internal child-table link, not the Pick List parent reference, so
one Delivery Note can safely point to multiple Pick Lists.
"""
from frappe import _


def get_data(data):
    data.setdefault("internal_links", {})["Pick List"] = ["items", "against_pick_list"]
    groups = data.setdefault("transactions", [])
    if not any("Pick List" in group.get("items", []) for group in groups):
        groups.append({"label": _("Picking"), "items": ["Pick List"]})
    return data
