"""Policy resolution independent of Frappe; no implicit category activation."""
from datetime import date



def resolve_policy(mappings, company, item, item_groups, warehouse, warehouse_groups, as_of):
    """Resolve explicitly enabled mappings; ancestors supplied by caller."""
    candidates = []
    for row in mappings:
        if not row.get("enabled") or row.get("company") != company:
            continue
        if row.get("effective_from") and date.fromisoformat(str(row["effective_from"])) > as_of:
            continue
        if row.get("effective_to") and date.fromisoformat(str(row["effective_to"])) < as_of:
            continue
        code, group, wh = row.get("item_code"), row.get("item_group"), row.get("warehouse")
        if code and code != item:
            continue
        if group and not (group == item_groups[0] or
                          row.get("include_item_descendants") and group in item_groups):
            continue
        if wh and not (wh == warehouse or
                       row.get("include_warehouse_descendants") and wh in warehouse_groups):
            continue
        if code and wh:
            specificity = 4
        elif group and wh and not code:
            specificity = 3
        elif group and not wh and not code:
            specificity = 2
        elif wh and not group and not code:
            specificity = 1
        else:
            continue
        candidates.append(((specificity, int(row.get("priority") or 0)), row))
    if not candidates:
        return None
    highest = max(score for score, _ in candidates)
    winners = [row for score, row in candidates if score == highest]
    if len(winners) != 1:
        raise ValueError("Conflicting reorder policy mappings")
    return winners[0]


def eligible_category(policy):
    return bool(policy.get("enabled") and policy.get("inventory_category") == "FG")


LEGACY_SCOPE_FIELDS = ("item_code", "item_group", "include_item_descendants",
                       "warehouse", "include_warehouse_descendants")


def mapping_warehouses(mapping):
    return [row.get("warehouse") for row in mapping.get("warehouses") or []]


def reorder_scope(warehouses, warehouse_rows):
    """Resolve leaf scope plus ancestors; reject an incomplete or cyclic tree."""
    parents = {row.get("name"): row.get("parent_warehouse") for row in warehouse_rows}
    scope = set(warehouses)
    for warehouse in warehouses:
        seen = set()
        current = warehouse
        while current:
            if current in seen or current not in parents:
                raise ValueError("Invalid warehouse hierarchy: " + str(current))
            seen.add(current)
            scope.add(current)
            current = parents[current]
    return scope, set(parents)


def reorder_row_overlaps(row, warehouses, scope):
    """An unrelated warehouse group is not a conflict; unknown groups fail closed."""
    ancestors, known = scope
    group = row.get("warehouse_group")
    return (row.get("warehouse") in warehouses
            or bool(group and (group in ancestors or group not in known)))


def reviewed_preserved_row(row, owned, mapping, warehouses):
    """Only a marked Guyong row with a valid managed Sta Clara counterpart is excluded."""
    return bool(owned and owned.get("custom_managed_reorder")
        and owned.get("custom_reorder_mapping") == mapping
        and owned.get("warehouse") == "FG - Sta Clara"
        and owned.get("material_request_type") == "Manufacture"
        and set(warehouses) == {"FG - Sta Clara", "FG - Guyong"}
        and row.get("warehouse") == "FG - Guyong"
        and row.get("warehouse_group") == "FG - Guyong"
        and row.get("material_request_type") == "Manufacture"
        and not row.get("custom_managed_reorder")
        and not row.get("custom_reorder_mapping")
        and not row.get("custom_reorder_history")
        and row.get("custom_reorder_excluded_mapping") == mapping)


def is_v2_mapping(mapping):
    return bool(mapping_warehouses(mapping) and
                (not any(mapping.get(k) for k in LEGACY_SCOPE_FIELDS)
                 or mapping.get("legacy_scope_reviewed")))


def active_on(row, as_of):
    return bool(row.get("enabled") and
                (not row.get("effective_from") or date.fromisoformat(str(row["effective_from"])) <= as_of) and
                (not row.get("effective_to") or date.fromisoformat(str(row["effective_to"])) >= as_of))


def classification_period_conflicts(left, right):
    if not left.get("enabled") or not right.get("enabled") or left.get("name") == right.get("name"):
        return False
    if any(left.get(k) != right.get(k) for k in ("company", "inventory_group", "inventory_type")):
        return False
    start = lambda r: date.fromisoformat(str(r["effective_from"])) if r.get("effective_from") else date.min
    end = lambda r: date.fromisoformat(str(r["effective_to"])) if r.get("effective_to") else date.max
    return max(start(left), start(right)) <= min(end(left), end(right))


def mapping_conflicts(left, right):
    """Same classification and dates may coexist only for disjoint reviewed leaf scopes."""
    if not classification_period_conflicts(left, right):
        return False
    if not is_v2_mapping(left) or not is_v2_mapping(right):
        return True
    a, b = mapping_warehouses(left), mapping_warehouses(right)
    if (not all(a) or not all(b) or len(a) != len(set(a)) or len(b) != len(set(b))
            or left.get("replenishment_warehouse") not in a
            or right.get("replenishment_warehouse") not in b):
        return True
    return bool(set(a).intersection(b))


def validate_scope(mapping, warehouses):
    names = mapping_warehouses(mapping)
    if not names or not all(names) or len(names) != len(set(names)):
        raise ValueError("Select distinct warehouses for the mapping")
    if mapping.get("replenishment_warehouse") not in names:
        raise ValueError("Replenishment Warehouse must be one of the selected warehouses")
    if (mapping.get("effective_from") and mapping.get("effective_to") and
            str(mapping["effective_from"]) > str(mapping["effective_to"])):
        raise ValueError("Effective To cannot precede Effective From")
    for name in names:
        wh = warehouses.get(name)
        if not wh or wh.get("company") != mapping.get("company") or wh.get("disabled") or wh.get("is_group"):
            raise ValueError("Select only enabled, non-group warehouses belonging to the company: " + str(name))
    if not is_v2_mapping(mapping):
        raise ValueError("Legacy scope requires explicit review before using the V2 warehouse scope")


def production_mode(inventory_group):
    return "Make to Stock" if inventory_group == "FG" else "Make to Order"


def validate_mapping(doc, method=None):
    import frappe
    # Serialize all mapping edits for a company, including inserts and reactivation.
    # Company rows exist before mappings, so two concurrent new mappings cannot race.
    frappe.db.sql("SELECT name FROM `tabCompany` WHERE name=%s FOR UPDATE", doc.company)
    policy = frappe.get_doc("Reorder Policy", doc.policy, for_update=True)
    doc.inventory_group = policy.inventory_category
    doc.inventory_type = policy.inventory_type
    if not doc.inventory_group or not doc.inventory_type:
        frappe.throw("Policy must specify Inventory Group and Inventory Type")
    # Disabled legacy documents remain editable for audit without inventing a scope.
    if not doc.enabled and not mapping_warehouses(doc):
        return
    warehouses = {r.name:r for r in frappe.get_all("Warehouse", filters={"name":["in",mapping_warehouses(doc)]},
        fields=["name","company","disabled","is_group"])}
    try:
        validate_scope(doc, warehouses)
        if doc.get("transfer_source_warehouse"):
            from qcmc_logic.dynamic_reorder_transfer import validate_transfer_source
            validate_transfer_source(doc.company, doc.transfer_source_warehouse,
                doc.replenishment_warehouse, mapping_warehouses(doc), read_only=False)
        # Locking/current reads remain correct under MariaDB REPEATABLE READ.
        others = frappe.db.sql("""
            SELECT m.*, p.inventory_category inventory_group, p.inventory_type
            FROM `tabReorder Policy Mapping` m JOIN `tabReorder Policy` p ON p.name=m.policy
            WHERE m.company=%s AND m.enabled=1 FOR UPDATE
        """, (doc.company,), as_dict=True)
        for other in others:
            if not classification_period_conflicts(doc, other):
                continue
            other["warehouses"] = frappe.db.sql("""
                SELECT warehouse FROM `tabReorder Mapping Warehouse`
                WHERE parent=%s AND parenttype='Reorder Policy Mapping'
                  AND parentfield='warehouses' FOR UPDATE
            """, (other.name,), as_dict=True)
            if mapping_conflicts(doc, other):
                raise ValueError("Overlapping active Reorder Policy Mapping: " + other.name)
    except ValueError as exc:
        frappe.throw(str(exc))
    doc.migration_review_required = 0


def validate_policy(doc, method=None):
    import frappe
    frappe.db.sql("SELECT name FROM `tabReorder Policy` WHERE name=%s FOR UPDATE", doc.name)
    old = doc.get_doc_before_save()
    if old and any(doc.get(k) != old.get(k) for k in ("inventory_category","inventory_type")):
        if frappe.db.sql("SELECT name FROM `tabReorder Policy Mapping` WHERE policy=%s AND enabled=1 FOR UPDATE", (doc.name,)):
            frappe.throw("Disable active mappings before changing policy Inventory Group or Inventory Type")


def validate_override(doc, method=None):
    import frappe
    mapping = frappe.get_doc("Reorder Policy Mapping", doc.mapping) if doc.get("mapping") else None
    if not mapping:
        if doc.enabled:
            frappe.throw("An enabled override requires an explicit V2 mapping")
        return
    frappe.db.sql("SELECT name FROM `tabCompany` WHERE name=%s FOR UPDATE", doc.company)
    mapping = frappe.get_doc("Reorder Policy Mapping", doc.mapping, for_update=True)
    if doc.get("warehouse") and not doc.get("legacy_scope_reviewed"):
        frappe.throw("Legacy override warehouse scope requires explicit mapping-wide review")
    if not is_v2_mapping(mapping) or doc.company != mapping.company:
        frappe.throw("Override must use a reviewed V2 mapping belonging to the company")
    policy = frappe.get_doc("Reorder Policy", mapping.policy, for_update=True)
    item = frappe.get_doc("Item", doc.item_code)
    if (item.custom_inventory_group, item.custom_inventory_type_) != (policy.inventory_category, policy.inventory_type):
        frappe.throw("Override item classification must match the mapping policy")
    if doc.get("policy"):
        alternate = frappe.get_doc("Reorder Policy", doc.policy, for_update=True)
        if (alternate.inventory_category, alternate.inventory_type) != (policy.inventory_category, policy.inventory_type):
            frappe.throw("Override policy must retain the mapping classification")
    if doc.get("effective_from") and doc.get("effective_to") and str(doc.effective_from) > str(doc.effective_to):
        frappe.throw("Effective To cannot precede Effective From")
    for other in frappe.db.sql("SELECT * FROM `tabItem Reorder Override` WHERE mapping=%s AND item_code=%s AND enabled=1 FOR UPDATE", (doc.mapping,doc.item_code),as_dict=True):
        a=dict(doc.as_dict(),inventory_group=doc.item_code,inventory_type=doc.mapping)
        b=dict(other,inventory_group=doc.item_code,inventory_type=doc.mapping)
        if classification_period_conflicts(a,b):
            frappe.throw("Overlapping active item overrides for this mapping")
