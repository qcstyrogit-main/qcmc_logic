"""Policy resolution independent of Frappe; no implicit category activation."""
from datetime import date

CATEGORIES = ("Finished Goods", "Raw Materials", "Factory Supplies", "Office Supplies", "Maintenance Stock Room")


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
    return bool(policy.get("enabled") and policy.get("inventory_category") == "Finished Goods")
