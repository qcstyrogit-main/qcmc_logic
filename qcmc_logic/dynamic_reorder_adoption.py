"""Reviewed import inventory and explicitly authorized ownership adoption.

No policies, mappings, reorder values, history or Material Requests are created here.
The adoption transaction is caller-committed; dry-run is the default.
"""
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
import hashlib
import json

GROUPS = {
    "FG - Bacolod - MC": (47, "Transfer"),
    "FG - CDO - MC": (43, "Transfer"),
    "FG - Laguna - MC": (45, "Transfer"),
    "FG - Cebu - MC": (95, "Transfer"),
    "FG - Davao - MC": (57, "Transfer"),
    "FG - EDSA": (55, "Manufacture"),
    "FG - Iloilo - MC": (69, "Transfer"),
    "FG - La Union - MC": (24, "Transfer"),
    "FG - MC1": (149, "Manufacture"),
    "FG - Pampanga - MC": (30, "Transfer"),
    "FG - Quezon - MC": (19, "Transfer"),
    "FG - Sta Clara": (207, "Manufacture"),
    "FG - Zamboanga - MC": (41, "Transfer"),
}
PRESERVED = {"FG - Guyong": (207, "Manufacture"),
             "Motorpool - EDSA": (1, "Purchase"),
             "Stockroom - EDSA": (1, "Purchase")}


def inventory_plan(rows, groups=None, preserved=None):
    """Classify existing rows without inferring policy parameters or ownership."""
    groups = GROUPS if groups is None else groups
    preserved = PRESERVED if preserved is None else preserved
    counts, classifications, problems = Counter(), Counter(), []
    candidates, retained, already_managed, guyong = [], [], [], []
    by_pair = defaultdict(list)
    for row in rows:
        by_pair[(row.get("parent"), row.get("warehouse"))].append(row)
    for row in rows:
        wh, item, name = (row.get(k) for k in ("warehouse", "parent", "name"))
        if wh not in groups and wh not in preserved:
            problems.append(dict(row=name, reason="Unexpected warehouse"))
            continue
        counts[wh] += 1
        expected_type = (groups if wh in groups else preserved)[wh][1]
        issues = []
        if len(by_pair[(item, wh)]) != 1:
            issues.append("Duplicate item/warehouse")
        if row.get("material_request_type") != expected_type:
            issues.append("Unexpected request type")
        if row.get("warehouse_group") != wh:
            issues.append("Warehouse group differs from reviewed import")
        if not row.get("warehouse_company") or row.get("warehouse_disabled") or row.get("warehouse_is_group"):
            issues.append("Invalid warehouse")
        expected_company = ("Multiplast Corporation" if wh.endswith(" - MC") or wh == "FG - MC1"
                            else "QC Styropackaging Corporation")
        if wh in GROUPS or wh in PRESERVED:
            if row.get("warehouse_company") != expected_company:
                issues.append("Warehouse company differs from reviewed import")
        if wh in preserved:
            if row.get("custom_managed_reorder") or row.get("custom_reorder_mapping") or row.get("custom_reorder_history"):
                issues.append("Preserved row already has custom ownership")
            if wh == "FG - Guyong" and len(by_pair[(item, "FG - Sta Clara")]) != 1:
                issues.append("Guyong has no unique Sta Clara counterpart")
            if wh != "FG - Guyong" and item != "RGP72CB228":
                issues.append("Unexpected preserved Purchase item")
            if row.get("custom_reorder_excluded_mapping"):
                issues.append("Preserved row already marked; reconcile separately")
            if wh == "FG - Guyong":
                guyong.append(dict(row=name, item=item, warehouse=wh,
                    reorder_level=str(row.get("warehouse_reorder_level")),
                    reorder_qty=str(row.get("warehouse_reorder_qty"))))
            retained.append(name)
        else:
            if row.get("custom_reorder_excluded_mapping"):
                issues.append("Candidate row has exclusion marker")
            if row.get("inventory_group") != "FG" or not row.get("inventory_type"):
                issues.append("Missing or unsupported item classification")
            if row.get("item_disabled") or not row.get("is_stock_item") or row.get("has_variants"):
                issues.append("Item not eligible")
            try:
                for field in ("warehouse_reorder_level", "warehouse_reorder_qty"):
                    value = Decimal(str(row.get(field)))
                    if not value.is_finite() or value < 0:
                        raise ValueError()
            except (ValueError, InvalidOperation, TypeError):
                issues.append("Invalid reorder values")
            managed = bool(row.get("custom_managed_reorder"))
            linked = bool(row.get("custom_reorder_mapping"))
            if managed != linked or (row.get("custom_reorder_history") and not managed):
                issues.append("Inconsistent existing ownership")
            if not issues:
                if managed:
                    already_managed.append(name)
                else:
                    candidates.append(dict(row=name, item=item, warehouse=wh,
                        company=row["warehouse_company"], inventory_group=row["inventory_group"],
                        inventory_type=row["inventory_type"], request_type=expected_type,
                        reorder_level=str(row["warehouse_reorder_level"]),
                        reorder_qty=str(row["warehouse_reorder_qty"])))
                classifications[(wh, row["warehouse_company"], row["inventory_group"],
                                 row["inventory_type"], expected_type)] += 1
        for issue in issues:
            problems.append(dict(row=name, item=item, warehouse=wh, reason=issue))
    differences = [dict(warehouse=wh, expected=expected, actual=counts[wh])
                   for wh, (expected, _) in {**groups, **preserved}.items()
                   if counts[wh] != expected]
    return dict(total=len(rows), eligible=len(candidates), already_managed=len(already_managed),
                preserved=len(retained), counts=dict(sorted(counts.items())),
                classification_groups=[dict(warehouse=k[0], company=k[1], inventory_group=k[2],
                    inventory_type=k[3], request_type=k[4], count=v)
                    for k,v in sorted(classifications.items())],
                count_differences=differences, issues=problems,
                candidates=candidates, preserved_rows=retained, guyong=guyong,
                ready_for_mapping_review=not problems and not differences)


def _read_inventory_rows():
    """Read existing Item Reorder rows with item and warehouse metadata."""
    import frappe
    return frappe.db.sql("""
        SELECT r.name, r.parent, r.warehouse, r.warehouse_group,
               r.material_request_type, r.warehouse_reorder_level, r.warehouse_reorder_qty,
               r.custom_managed_reorder, r.custom_reorder_mapping, r.custom_reorder_history,
               r.custom_reorder_excluded_mapping,
               i.custom_inventory_group AS inventory_group,
               i.custom_inventory_type_ AS inventory_type, i.disabled AS item_disabled,
               i.is_stock_item, i.has_variants, w.company AS warehouse_company,
               w.disabled AS warehouse_disabled, w.is_group AS warehouse_is_group
        FROM `tabItem Reorder` r
        LEFT JOIN `tabItem` i ON i.name=r.parent
        LEFT JOIN `tabWarehouse` w ON w.name=r.warehouse
        WHERE r.parenttype='Item' AND r.parentfield='reorder_levels'
        ORDER BY r.warehouse, r.parent, r.name
    """, as_dict=True)


def inspect_import():
    """Administrator-only, read-only inventory; never applies changes."""
    import frappe
    if frappe.session.user != "Administrator":
        frappe.throw("Administrator access required", frappe.PermissionError)
    return inventory_plan(_read_inventory_rows())


def expected_scope(warehouse):
    return {
        "FG - Sta Clara": {"FG - Sta Clara", "FG - Guyong"},
        "FG - MC1": {"FG - MC1", "FG - MC2"},
    }.get(warehouse, {warehouse})


def mapping_plan(inventory, mappings):
    """Match reviewed rows to explicit, enabled mappings; never invent a policy."""
    issues = list(inventory["issues"]) + list(inventory["count_differences"])
    changes = []
    by_scope = defaultdict(list)
    for m in mappings:
        if not m.get("enabled") or not m.get("policy_enabled"):
            continue
        by_scope[(m.get("company"), m.get("inventory_group"), m.get("inventory_type"),
                  m.get("replenishment_warehouse"))].append(m)
    for row in inventory["candidates"]:
        scope = (row["company"], row["inventory_group"], row["inventory_type"], row["warehouse"])
        matches = by_scope[scope]
        if len(matches) != 1:
            issues.append(dict(row=row["row"], reason="Exactly one active mapping required"))
            continue
        m = matches[0]
        if (set(m.get("warehouses") or []) != expected_scope(row["warehouse"])
                or len(m.get("warehouses") or []) != len(expected_scope(row["warehouse"]))
                or m.get("automatic_draft_replenishment")
                or m.get("request_type") not in ("Preserve", row["request_type"])):
            issues.append(dict(row=row["row"], reason="Mapping scope, request type or automatic mode requires review"))
            continue
        changes.append(dict(row, mapping=m["name"]))
    changes.sort(key=lambda r: r["row"])
    sta = {r["item"]: r for r in changes if r["warehouse"] == "FG - Sta Clara"}
    exclusions = []
    for row in inventory.get("guyong", []):
        counterpart = sta.get(row["item"])
        if not counterpart:
            issues.append(dict(row=row["row"], reason="No approved Sta Clara adoption candidate"))
            continue
        exclusions.append(dict(row, mapping=counterpart["mapping"]))
    exclusions.sort(key=lambda r: r["row"])
    digest = hashlib.sha256(json.dumps(dict(changes=changes, exclusions=exclusions),
                                      sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    # The first adoption is all-or-nothing; already-managed rows must be reviewed separately.
    if inventory["already_managed"]:
        issues.append(dict(reason="Existing managed rows require separate reconciliation"))
    return dict(ready=not issues and len(changes)==inventory["eligible"] and bool(changes),
                count=len(changes), issues=issues, digest=digest, changes=changes,
                exclusions=exclusions, exclusion_count=len(exclusions))


def _require_disabled():
    import frappe
    from frappe.utils import cint
    settings = frappe.get_single("Reorder Settings")
    if (settings.enabled or not settings.preview_only or settings.automatic_update_enabled
            or settings.get("replenishment_mode") != "Disabled"
            or cint(frappe.db.get_single_value("Stock Settings", "auto_indent"))):
        frappe.throw("Adoption requires disabled reorder and replenishment with preview-only enabled")


def _mapping_records():
    import frappe
    from qcmc_logic.dynamic_reorder_clock import business_date
    from qcmc_logic.dynamic_reorder_policy import active_on, mapping_warehouses
    from qcmc_logic.dynamic_reorder_service import load_mapping
    result = []
    today = business_date()
    for ref in frappe.get_all("Reorder Policy Mapping", filters={"enabled":1},
                              fields=["name","company"], order_by="name"):
        mapping, policy = load_mapping(ref.company, ref.name, today)
        if active_on(mapping, today):
            result.append(dict(name=mapping.name, enabled=1, company=mapping.company,
                policy_enabled=policy.enabled, inventory_group=policy.inventory_category,
                inventory_type=policy.inventory_type, request_type=policy.material_request_type,
                replenishment_warehouse=mapping.replenishment_warehouse,
                automatic_draft_replenishment=mapping.get("automatic_draft_replenishment"),
                warehouses=mapping_warehouses(mapping)))
    return result


def adoption_preview():
    """Read-only mapping plan, including exact row identities and approval digest."""
    return mapping_plan(inspect_import(), _mapping_records())


def adopt_existing(expected_digest=None, apply=False):
    """Console-only adoption. No commit; caller must review and commit explicitly.

    Run only during a maintenance window with item and mapping edits suspended.
    """
    import frappe
    if frappe.session.user != "Administrator" or getattr(frappe.local, "request", None):
        frappe.throw("Administrator console required")
    if not apply:
        return adoption_preview()
    _require_disabled()
    if not expected_digest:
        frappe.throw("Reviewed adoption digest required")
    # Lock the same company and item records used by approval and mapping edits.
    for company in ("Multiplast Corporation", "QC Styropackaging Corporation"):
        frappe.db.sql("SELECT name FROM `tabCompany` WHERE name=%s FOR UPDATE", (company,))
    frappe.db.sql("""SELECT DISTINCT i.name FROM `tabItem` i
        JOIN `tabItem Reorder` r ON r.parent=i.name
        WHERE r.parenttype='Item' AND r.parentfield='reorder_levels'
        ORDER BY i.name FOR UPDATE""")
    frappe.db.sql("""SELECT name FROM `tabItem Reorder`
        WHERE parenttype='Item' AND parentfield='reorder_levels' ORDER BY name FOR UPDATE""")
    plan = adoption_preview()
    if not plan["ready"] or plan["digest"] != expected_digest:
        frappe.throw("Adoption plan changed or contains unresolved issues; generate a fresh preview")
    frappe.db.savepoint("qcmc_reorder_adoption")
    try:
        for change in plan["changes"]:
            current = frappe.db.get_value("Item Reorder", change["row"],
                ["parent","warehouse","warehouse_reorder_level","warehouse_reorder_qty",
                 "material_request_type","custom_managed_reorder","custom_reorder_mapping",
                 "custom_reorder_history","custom_reorder_excluded_mapping","warehouse_group"], as_dict=True, for_update=True)
            if (not current or current.parent != change["item"] or current.warehouse != change["warehouse"]
                    or current.material_request_type != change["request_type"]
                    or Decimal(str(current.warehouse_reorder_level)) != Decimal(change["reorder_level"])
                    or Decimal(str(current.warehouse_reorder_qty)) != Decimal(change["reorder_qty"])
                    or current.warehouse_group != change["warehouse"]
                    or current.custom_managed_reorder or current.custom_reorder_mapping
                    or current.custom_reorder_history or current.custom_reorder_excluded_mapping):
                frappe.throw("Reorder row changed: " + change["row"])
            frappe.db.set_value("Item Reorder", change["row"],
                dict(custom_managed_reorder=1, custom_reorder_mapping=change["mapping"]))
        for change in plan["exclusions"]:
            current = frappe.db.get_value("Item Reorder", change["row"],
                ["parent","warehouse","warehouse_group","material_request_type",
                 "warehouse_reorder_level","warehouse_reorder_qty","custom_managed_reorder",
                 "custom_reorder_mapping","custom_reorder_history","custom_reorder_excluded_mapping"],
                as_dict=True, for_update=True)
            if (not current or current.parent != change["item"] or current.warehouse != "FG - Guyong"
                    or current.warehouse_group != "FG - Guyong" or current.material_request_type != "Manufacture"
                    or str(current.warehouse_reorder_level) != change["reorder_level"]
                    or str(current.warehouse_reorder_qty) != change["reorder_qty"]
                    or current.custom_managed_reorder or current.custom_reorder_mapping
                    or current.custom_reorder_history or current.custom_reorder_excluded_mapping):
                frappe.throw("Preserved Guyong row changed: " + change["row"])
            frappe.db.set_value("Item Reorder", change["row"],
                "custom_reorder_excluded_mapping", change["mapping"])
        _require_disabled()
    except Exception:
        frappe.db.rollback(save_point="qcmc_reorder_adoption")
        raise
    return dict(status="Applied - Not Committed", count=plan["count"],
                excluded=plan["exclusion_count"], digest=plan["digest"])

