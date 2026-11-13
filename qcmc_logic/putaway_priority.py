"""Automatic putaway positions and explicit, transaction-safe location ordering."""

import hashlib
import json

import frappe
from frappe import _
from frappe.utils import cint

from qcmc_logic.utils import check_warehouse_access


def group_key(rule):
    unrestricted = cint(rule.get("custom_no_item_restriction"))
    return (rule.get("company"), rule.get("warehouse"), unrestricted,
            "" if unrestricted else (rule.get("item_code") or ""))


def _lock_warehouses(warehouses):
    # Stable existing rows also serialize the first rule in an empty group.
    # Acquire these before any rule row, in one consistent warehouse order.
    for warehouse in sorted({value for value in warehouses if value}):
        frappe.db.sql("select name from `tabWarehouse` where name = %s for update", (warehouse,))


def lock_rule_warehouses(rule):
    old_warehouse = None
    if not rule.is_new():
        old_warehouse = frappe.db.get_value("Putaway Rule", rule.name, "warehouse")
    _lock_warehouses([rule.get("warehouse"), old_warehouse])


def get_group_rows(rule, for_update=False):
    company, warehouse, unrestricted, item = group_key(rule)
    return frappe.db.sql(
        """select * from `tabPutaway Rule`
           where company = %(company)s and warehouse = %(warehouse)s
             and coalesce(custom_no_item_restriction, 0) = %(unrestricted)s
             and (%(unrestricted)s = 1 or coalesce(item_code, '') = %(item)s)
           order by priority asc, creation asc, name asc"""
        + (" for update" if for_update else ""),
        {"company": company, "warehouse": warehouse, "unrestricted": unrestricted, "item": item},
        as_dict=True,
    )


def assign_priority(rule):
    previous = rule.get_doc_before_save()
    if previous and group_key(previous) == group_key(rule):
        rule.priority = previous.priority
        return
    if not rule.get("company") or not rule.get("warehouse"):
        return
    if not rule.get("custom_no_item_restriction") and not rule.get("item_code"):
        return
    rows = get_group_rows(rule, for_update=True)
    rule.priority = max((cint(row.get("priority")) for row in rows if row.get("name") != rule.name), default=0) + 1


def group_version(rows):
    data = [(row["name"], row.get("priority"), str(row.get("modified") or "")) for row in rows]
    return hashlib.sha256(json.dumps(data, ensure_ascii=False).encode()).hexdigest()


def validate_order(ordered_rules, rows):
    names = frappe.parse_json(ordered_rules) if isinstance(ordered_rules, str) else ordered_rules
    if not isinstance(names, list) or not all(isinstance(name, str) for name in names):
        frappe.throw(_("Provide the complete location order."))
    if len(names) != len(rows) or len(set(names)) != len(names) or set(names) != {row["name"] for row in rows}:
        frappe.throw(_("The order must contain each rule in this group exactly once. Reload the location order."))
    return names


def _check_access(rule, permission="read"):
    rule.check_permission(permission)
    if not check_warehouse_access(frappe.session.user, rule.warehouse) or not frappe.has_permission(
        "Warehouse", "read", doc=rule.warehouse
    ):
        frappe.throw(_("You do not have access to this Warehouse."), frappe.PermissionError)


def _check_group_access(rows, permission):
    for row in rows:
        doc = frappe.get_doc({**row, "doctype": "Putaway Rule"})
        if not frappe.has_permission("Putaway Rule", permission, doc=doc):
            frappe.throw(_("You need access to every rule in this group to manage its location order."), frappe.PermissionError)


def _order_response(rule, rows):
    return {
        "company": rule.company, "warehouse": rule.warehouse,
        "item_code": rule.item_code or "", "unrestricted": cint(rule.get("custom_no_item_restriction")),
        "version": group_version(rows),
        "rules": [{"rule": row.name, "location": row.get("location") or "",
                   "priority": row.priority, "disabled": cint(row.get("disable"))} for row in rows],
    }


@frappe.whitelist()
def get_priority_order(rule_name):
    rule = frappe.get_doc("Putaway Rule", rule_name)
    _check_access(rule)
    rows = get_group_rows(rule)
    _check_group_access(rows, "read")
    return _order_response(rule, rows)


@frappe.whitelist(methods=["POST"])
def save_priority_order(rule_name, ordered_rules, version):
    rule = frappe.get_doc("Putaway Rule", rule_name)
    _check_access(rule, "write")
    warehouse = rule.warehouse
    _lock_warehouses([warehouse])
    rule = frappe.get_doc("Putaway Rule", rule_name, for_update=True)
    _check_access(rule, "write")
    if rule.warehouse != warehouse:
        frappe.throw(_("This rule changed Warehouse. Reload the location order."), frappe.TimestampMismatchError)
    rows = get_group_rows(rule, for_update=True)
    if version != group_version(rows):
        frappe.throw(_("The location order has changed. Reload it before saving."), frappe.TimestampMismatchError)
    names = validate_order(ordered_rules, rows)
    _check_group_access(rows, "write")
    existing = {row.name: row for row in rows}
    for position, name in enumerate(names, 1):
        if cint(existing[name].priority) != position:
            frappe.db.set_value("Putaway Rule", name, "priority", position)
            frappe.clear_document_cache("Putaway Rule", name)
    return {"updated": len(names)}
