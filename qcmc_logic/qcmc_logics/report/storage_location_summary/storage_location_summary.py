"""Current physical stock, grouped by the Storage Location hierarchy."""

import json
from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import cint, flt

from qcmc_logic.qcmc_logics.doctype.storage_location.storage_location import natural_location_sort_key
from qcmc_logic.utils import check_warehouse_access


def get_balances(warehouse):
    """Use the exact same current quantity as Storage Location Item Balances.

    The bulk location listing supplies the item/location combinations; current
    quantities account for posted Warehouse Transfer OUT through the shared
    physical-balance reader. Do not subtract WT movements a second time here.
    """
    from qcmc_logic.api.stock_reconciliation import (
        _get_physical_location_balances,
        _current_inventory_quantity,
    )

    balances = _get_physical_location_balances(warehouse)
    corrected = []
    cache = {}
    seen = set()
    for row in balances:
        location = row.get("location")
        item_code = row.get("item_code")
        if not location or not item_code:
            continue
        key = (item_code, warehouse, location)
        if key in seen:
            continue
        seen.add(key)
        if key not in cache:
            cache[key] = flt(_current_inventory_quantity(item_code, warehouse, location))
        qty = cache[key]
        if qty <= 0.000000001:
            continue
        entry = dict(row)
        entry["quantity"] = qty
        corrected.append(entry)
    return corrected


def get_capacity_rules(warehouse):
    meta = frappe.get_meta("Putaway Rule")
    if not meta.has_field("location"):
        return []
    fields = ["name", "location", "capacity", "stock_capacity", "priority"]
    fields += [field for field in (
        "custom_no_item_restriction", "custom_no_capacity_restriction", "stock_uom", "uom",
    ) if meta.has_field(field)]
    return frappe.get_all(
        "Putaway Rule", filters={"warehouse": warehouse, "disable": 0},
        fields=fields, limit_page_length=0,
    )


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

    location_fields = ["name", "location_name", "location_type", "parent_storage_location", "custom_warehouse", "is_group"]
    location_meta = frappe.get_meta("Storage Location")
    location_fields += [field for field in ("storage_capacity", "custom_storage_capacity") if location_meta.has_field(field)]
    locations = frappe.get_list(
        "Storage Location", filters={"disabled": 0},
        fields=location_fields,
        order_by="lft", limit_page_length=0,
    )
    balances = get_balances(warehouse)
    item_codes = sorted({row["item_code"] for row in balances})
    permitted_items = set(frappe.get_list(
        "Item", filters={"name": ["in", item_codes]}, pluck="name", limit_page_length=0,
    )) if item_codes else set()
    balances = [row for row in balances if row["item_code"] in permitted_items]
    data = build_tree(locations, balances, filters, capacity_rules=get_capacity_rules(warehouse),
                      usage_complete=set(item_codes) <= permitted_items)
    message = _(
        "Current physical stock including posted Warehouse Transfer OUT, allocations, location transfers and physical counts. "
        "Parent rows include their descendants. Mixed units are listed separately in Quantity by UOM. "
        "Capacity usage includes all stock, regardless of the Item filter. Blank capacities are unconfigured or cannot be combined."
    )
    return get_columns(), data, message


def build_tree(locations, balances, filters, capacity_rules=(), usage_complete=True):
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

    capacity_metrics = get_capacity_metrics(
        nodes, children, scope, eligible, balances, warehouse, capacity_rules, usage_complete,
    )

    data = []

    def append_node(name, indent=0, parent=None):
        location = nodes[name]
        units, items = summaries[name]
        node_id = json.dumps(["location", name])
        metrics = capacity_metrics.get(name, {})
        if cint(location.get("is_group")) or children[name]:
            metrics = {
                "capacity": None, "used_capacity": None, "available_capacity": None,
                "use_percentage": None, "capacity_uom": "", "capacity_unlimited": False,
            }
        data.append({
            "node_id": node_id, "parent_node": parent, "indent": indent,
            "entry": name, "entry_type": "Storage Location",
            "description": location.get("location_name"), "location_type": location.get("location_type"),
            "warehouse": warehouse, "item_count": len(items),
            **metrics,
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
                "capacity": None, "used_capacity": None, "available_capacity": None, "use_percentage": None,
                "capacity_uom": "",
            })

    roots = sorted((name for name in visible if nodes[name].get("parent_storage_location") not in visible), key=sort_key)
    for name in roots:
        append_node(name)
    return data


def get_capacity_metrics(nodes, children, scope, eligible, balances, warehouse, rules, usage_complete):
    """Use all permitted stock and all eligible children, including hidden empty ones."""
    selected_rules = {}
    # Match the tree popup's rule precedence, using one warehouse-wide read.
    for rule in sorted(rules, key=lambda rule: (
        0 if rule.get("custom_no_capacity_restriction") else 1,
        0 if rule.get("custom_no_item_restriction") else 1,
        -flt(rule.get("stock_capacity") or rule.get("capacity")),
        flt(rule.get("priority")), rule["name"],
    )):
        selected_rules.setdefault(rule.get("location"), rule)

    relevant, occupancy, directly_occupied = set(), defaultdict(lambda: defaultdict(float)), set()
    for name in eligible:
        while name in scope and name not in relevant:
            relevant.add(name)
            name = nodes[name].get("parent_storage_location")
    for balance in balances:
        name = balance.get("location")
        if name not in eligible or balance.get("warehouse") != warehouse or flt(balance.get("quantity")) <= 0.000000001:
            continue
        directly_occupied.add(name)
        seen = set()
        while name in scope and name not in seen:
            seen.add(name)
            occupancy[name][balance.get("stock_uom") or ""] += flt(balance["quantity"])
            name = nodes[name].get("parent_storage_location")

    cache, visiting = {}, set()

    def effective_capacity(name):
        if name in cache:
            return cache[name]
        if name in visiting:
            frappe.throw(_("The Storage Location tree contains a circular parent relationship."))
        visiting.add(name)
        rule = selected_rules.get(name, {}) if name in eligible else {}
        unit = rule.get("stock_uom") or rule.get("uom") or ""
        if not unit and len(occupancy[name]) == 1:
            unit = next(iter(occupancy[name]))
        unlimited = bool(rule.get("custom_no_capacity_restriction"))
        capacity = flt(rule.get("stock_capacity") or rule.get("capacity"))
        if not capacity and not unlimited and name in eligible:
            capacity = next((flt(nodes[name].get(field)) for field in ("storage_capacity", "custom_storage_capacity") if flt(nodes[name].get(field)) > 0), 0)
        if not capacity and not unlimited and name not in directly_occupied:
            child_capacities = [effective_capacity(child) for child in children[name] if child in relevant]
            unlimited = any(child[2] for child in child_capacities)
            child_units = {child[1] for child in child_capacities if child[1]}
            if child_capacities and all(child[0] is not None for child in child_capacities) and len(child_units) <= 1:
                capacity = sum(child[0] for child in child_capacities)
                unit = next(iter(child_units), unit)
        cache[name] = (capacity if capacity > 0 and not unlimited else None, unit, unlimited)
        visiting.remove(name)
        return cache[name]

    metrics = {}
    for name in relevant:
        capacity, unit, unlimited = effective_capacity(name)
        units = occupancy[name]
        compatible = len(units) <= 1 and (not units or not unit or unit == next(iter(units)))
        used = sum(units.values()) if compatible and usage_complete else None
        available = max(capacity - used, 0) if capacity is not None and used is not None else None
        metrics[name] = {
            "capacity": capacity, "capacity_uom": unit, "capacity_unlimited": unlimited,
            "used_capacity": used, "available_capacity": available,
            "use_percentage": used / capacity * 100 if capacity and used is not None else None,
        }
    return metrics


def get_columns():
    return [
        {"fieldname": "entry", "label": _("Storage Location / Item"), "fieldtype": "Dynamic Link", "options": "entry_type", "width": 260},
        {"fieldname": "description", "label": _("Location Name / Item Name"), "fieldtype": "Data", "width": 300},
        {"fieldname": "location_type", "label": _("Location Type"), "fieldtype": "Data", "width": 110},
        {"fieldname": "warehouse", "label": _("Warehouse"), "fieldtype": "Link", "options": "Warehouse", "width": 160},
        {"fieldname": "item_count", "label": _("Distinct Items"), "fieldtype": "Int", "width": 110},
        {"fieldname": "stock_qty", "label": _("Stock Quantity"), "fieldtype": "Float", "width": 150},
        {"fieldname": "stock_uom", "label": _("Stock UOM"), "fieldtype": "Data", "width": 100},
        {"fieldname": "capacity_uom", "label": _("Capacity UOM"), "fieldtype": "Data", "width": 110},
        {"fieldname": "capacity", "label": _("Capacity"), "fieldtype": "Float", "width": 140},
        {"fieldname": "used_capacity", "label": _("Used Capacity"), "fieldtype": "Float", "width": 140},
        {"fieldname": "available_capacity", "label": _("Available Capacity"), "fieldtype": "Float", "width": 150},
        {"fieldname": "use_percentage", "label": _("Use Percentage"), "fieldtype": "Float", "width": 130},
        {"fieldname": "quantity_by_uom", "label": _("Quantity by UOM"), "fieldtype": "Data", "width": 230},
    ]
