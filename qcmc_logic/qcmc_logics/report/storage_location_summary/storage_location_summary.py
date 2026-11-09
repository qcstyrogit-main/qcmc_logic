"""Current physical stock, grouped by the Storage Location hierarchy."""

import json
from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import cint, flt

from qcmc_logic.qcmc_logics.doctype.storage_location.storage_location import natural_location_sort_key
from qcmc_logic.utils import check_warehouse_access


def get_balances(warehouse):
    from qcmc_logic.api.stock_reconciliation import _get_physical_location_balances

    return _get_physical_location_balances(warehouse)


def execute(filters=None):
    filters = frappe._dict(filters or {})
    if not frappe.has_permission("Storage Location", "report"):
        frappe.throw(_("You do not have permission to view Storage Locations."), frappe.PermissionError)
    warehouse = filters.get("warehouse")
    if not warehouse:
        frappe.throw(_("Warehouse is required."))
    if not check_warehouse_access(frappe.session.user, warehouse) or not frappe.has_permission(
        "Warehouse", "read", doc=warehouse
    ):
        frappe.throw(_("You do not have access to Warehouse {0}.").format(warehouse), frappe.PermissionError)

    locations = frappe.get_list(
        "Storage Location", filters={"disabled": 0},
        fields=["name", "location_name", "location_type", "parent_storage_location", "custom_warehouse", "is_group"],
        order_by="lft", limit_page_length=0,
    )
    balances = get_balances(warehouse)
    item_codes = sorted({row["item_code"] for row in balances})
    permitted_items = set(frappe.get_list(
        "Item", filters={"name": ["in", item_codes]}, pluck="name", limit_page_length=0,
    )) if item_codes else set()
    balances = [row for row in balances if row["item_code"] in permitted_items]
    data = build_tree(locations, balances, filters)
    message = _(
        "Current physical stock from allocations, location transfers and physical counts. "
        "Parent rows include their descendants. Mixed units are listed separately in Quantity by UOM."
    )
    return get_columns(), data, message


def build_tree(locations, balances, filters):
    """Aggregate only visible stock, keeping tree nodes and item rows distinct."""
    warehouse = filters["warehouse"]
    nodes = {row["name"]: row for row in locations if not cint(row.get("disabled"))}
    children = defaultdict(list)
    for name, row in nodes.items():
        children[row.get("parent_storage_location") or ""].append(name)
    sort_key = lambda name: (natural_location_sort_key(nodes[name].get("location_name")), natural_location_sort_key(name))
    for names in children.values():
        names.sort(key=sort_key)

    scope = set(nodes)
    branch = filters.get("storage_location")
    if branch:
        if branch not in nodes:
            frappe.throw(_("The selected Storage Location is disabled or unavailable."), frappe.PermissionError)
        scope, pending = set(), [branch]
        while pending:
            name = pending.pop()
            if name not in scope:
                scope.add(name)
                pending.extend(children[name])

    eligible = {name for name in scope if nodes[name].get("custom_warehouse") == warehouse}
    stock = defaultdict(dict)
    for balance in balances:
        name = balance.get("location")
        if name not in eligible or balance.get("warehouse") != warehouse:
            continue
        if filters.get("item_code") and balance["item_code"] != filters["item_code"]:
            continue
        quantity = flt(balance.get("quantity"))
        if quantity <= 0.000000001:
            continue
        key = (balance["item_code"], balance.get("stock_uom") or "")
        item = stock[name].setdefault(key, {
            "item_code": balance["item_code"], "item_name": balance.get("item_name") or balance["item_code"],
            "stock_uom": key[1], "stock_qty": 0,
        })
        item["stock_qty"] += quantity

    visible = set()
    seeds = eligible if cint(filters.get("show_empty_locations")) else set(stock)
    for name in seeds:
        while name in scope and name not in visible:
            visible.add(name)
            name = nodes[name].get("parent_storage_location")

    summaries, visiting = {}, set()

    def summarize(name):
        if name in visiting:
            frappe.throw(_("The Storage Location tree contains a circular parent relationship."))
        if name in summaries:
            return summaries[name]
        visiting.add(name)
        units, items = defaultdict(float), set()
        for item in stock[name].values():
            units[item["stock_uom"]] += item["stock_qty"]
            items.add(item["item_code"])
        for child in children[name]:
            if child in visible:
                child_units, child_items = summarize(child)
                for unit, quantity in child_units.items():
                    units[unit] += quantity
                items.update(child_items)
        visiting.remove(name)
        summaries[name] = units, items
        return units, items

    # Validate every retained node, including malformed cycles without roots.
    for name in visible:
        summarize(name)

    data = []

    def append_node(name, indent=0, parent=None):
        location = nodes[name]
        units, items = summaries[name]
        node_id = json.dumps(["location", name])
        data.append({
            "node_id": node_id, "parent_node": parent, "indent": indent,
            "entry": name, "entry_type": "Storage Location",
            "description": location.get("location_name"), "location_type": location.get("location_type"),
            "warehouse": warehouse, "item_count": len(items),
            "stock_qty": next(iter(units.values())) if len(units) == 1 else (None if units else 0),
            "stock_uom": next(iter(units)) if len(units) == 1 else (_("Mixed") if units else ""),
            "quantity_by_uom": "; ".join(
                f"{quantity:,.9f}".rstrip("0").rstrip(".") + f" {unit}"
                for unit, quantity in sorted(units.items())
            ),
        })
        for child in children[name]:
            if child in visible:
                append_node(child, indent + 1, node_id)
        for key, item in sorted(stock[name].items(), key=lambda pair: (natural_location_sort_key(pair[1]["item_name"]), pair[0])):
            data.append({
                "node_id": json.dumps(["item", name, *key]), "parent_node": node_id, "indent": indent + 1,
                "entry": item["item_code"], "entry_type": "Item", "description": item["item_name"],
                "location_type": "", "warehouse": warehouse, "item_count": 1,
                "stock_qty": item["stock_qty"], "stock_uom": item["stock_uom"], "quantity_by_uom": "",
            })

    roots = sorted((name for name in visible if nodes[name].get("parent_storage_location") not in visible), key=sort_key)
    for name in roots:
        append_node(name)
    return data


def get_columns():
    return [
        {"fieldname": "entry", "label": _("Storage Location / Item"), "fieldtype": "Dynamic Link", "options": "entry_type", "width": 260},
        {"fieldname": "description", "label": _("Location Name / Item Name"), "fieldtype": "Data", "width": 300},
        {"fieldname": "location_type", "label": _("Location Type"), "fieldtype": "Data", "width": 110},
        {"fieldname": "warehouse", "label": _("Warehouse"), "fieldtype": "Link", "options": "Warehouse", "width": 160},
        {"fieldname": "item_count", "label": _("Distinct Items"), "fieldtype": "Int", "width": 110},
        {"fieldname": "stock_qty", "label": _("Stock Quantity"), "fieldtype": "Float", "width": 150},
        {"fieldname": "stock_uom", "label": _("Stock UOM"), "fieldtype": "Data", "width": 100},
        {"fieldname": "quantity_by_uom", "label": _("Quantity by UOM"), "fieldtype": "Data", "width": 230},
    ]
