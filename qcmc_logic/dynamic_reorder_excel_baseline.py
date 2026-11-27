"""Console-only approval of the reconciled QC/MC Excel baseline.

Preview is read-only. Apply adopts the reviewed rows and records their existing
values, without recalculation, Material Requests or a commit. Run in maintenance.
"""
from collections import Counter, defaultdict
from decimal import Decimal
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import json

from qcmc_logic.dynamic_reorder_adoption import GROUPS, expected_scope

FILENAME = "Reorder_Baseline_QC_MC.xlsx"
CHECKSUM = "69716c6da89b3fb1d8aedb1487115be5e40ecfa8bd3d54320e5bde6b33de9fc3"
WAREHOUSES = {
    "33N35": "FG - Sta Clara", "QCEDS": "FG - EDSA", "MULTI": "FG - MC1",
    "BACOL": "FG - Bacolod - MC", "CDO": "FG - CDO - MC",
    "CEBU": "FG - Cebu - MC", "DAVAO": "FG - Davao - MC",
    "ILOIL": "FG - Iloilo - MC", "LAUNI": "FG - La Union - MC",
    "CALAB": "FG - Laguna - MC", "PAMPA": "FG - Pampanga - MC",
    "QUEZO": "FG - Quezon - MC", "ZAMBO": "FG - Zamboanga - MC",
    "STA CLARA - GUYONG": "FG - Sta Clara", "EDSA": "FG - EDSA",
}
POLICY_FIELDS = ("lead_time", "safety_days", "coverage_days", "minimum_stock", "maximum_stock",
    "moq", "order_multiple", "production_batch", "material_request_type", "demand_period_method",
    "rolling_days", "historical_months", "seasonal_profile", "demand_delivery",
    "demand_manufacture", "demand_intercompany", "demand_provincial", "deduct_returns")


def numeric(value, positive=False):
    n = Decimal(str(value))
    if not n.is_finite() or n < 0 or (positive and not n):
        raise ValueError("Invalid Excel quantity")
    return str(n.normalize())


def key(item, warehouse):
    return (str(item).strip().upper(), warehouse)


def read_workbook(data):
    from openpyxl import load_workbook
    if sha256(data).hexdigest() != CHECKSUM:
        raise ValueError("Workbook differs from the verified production baseline")
    wb = load_workbook(BytesIO(data), read_only=True, data_only=True)
    entries = {}
    counts = Counter()
    try:
        for sheet in ("QC", "MC"):
            rows = wb[sheet].iter_rows(values_only=True)
            headers = {str(v).strip().upper(): i for i,v in enumerate(next(rows)) if v}
            qty = "RQTY" if sheet == "QC" else "ROQ"
            for row in rows:
                if not row[headers["CWHOUSE"]]:
                    continue
                get = lambda field: row[headers[field]]
                wh = WAREHOUSES[str(get("CWHOUSE")).strip().upper()]
                ident = key(get("CPRODCODE"), wh)
                if not ident[0] or ident in entries:
                    raise ValueError("Duplicate or empty Excel item: " + str(ident))
                terms = dict(sheet=sheet, level=numeric(get("ROL"), True),
                    qty=numeric(get(qty), True), lead_days=None, safety_days=None,
                    minimum=None, maximum=None)
                if sheet == "QC":
                    terms.update(lead_days=numeric(get("LEADTIME")),
                        safety_days=numeric(get("SAFETYSTOCKS")),
                        minimum=numeric(get("NMININVTYLEVELQTY")),
                        maximum=numeric(get("NMAXINVTYLEVELQTY")))
                entries[ident] = terms
                counts[wh] += 1
    finally:
        wb.close()
    if counts != Counter({wh: n for wh,(n,_) in GROUPS.items()}):
        raise ValueError("Excel warehouse counts differ from the reviewed import")
    return entries


def reconcile(plan, entries, item_names):
    if not plan["ready"]:
        raise ValueError("Adoption plan not ready")
    names = defaultdict(list)
    for name in item_names:
        names[name.upper()].append(name)
    matched = set()
    for change in plan["changes"]:
        ident = key(change["item"], change["warehouse"])
        terms = entries.get(ident)
        if (ident in matched or not terms or names[ident[0]] != [change["item"]]
                or Decimal(terms["level"]) != Decimal(change["reorder_level"])
                or Decimal(terms["qty"]) != Decimal(change["reorder_qty"])):
            raise ValueError("Excel configuration mismatch: " + str(ident))
        matched.add(ident)
    if matched != set(entries):
        raise ValueError("Incomplete Excel baseline")
    for row in plan["exclusions"]:
        ident = key(row["item"], "FG - Sta Clara")
        terms = entries.get(ident)
        if (not terms or names[ident[0]] != [row["item"]]
                or Decimal(terms["level"]) != Decimal(row["reorder_level"])
                or Decimal(terms["qty"]) != Decimal(row["reorder_qty"])):
            raise ValueError("Preserved Guyong configuration mismatch: " + str(ident))


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def baseline_replenishment_terms(snapshot, history):
    """Read only the approved Excel terms, never substitute missing MC inputs."""
    terms = snapshot.get("excel_terms") or {}
    if (snapshot.get("workbook_sha256") != CHECKSUM
            or not snapshot.get("approval_digest")
            or Decimal(terms["level"]) != Decimal(str(history.recommended_level))
            or Decimal(terms["qty"]) != Decimal(str(history.recommended_qty))):
        raise ValueError("Excel approval snapshot mismatch")
    if terms["sheet"] not in ("QC", "MC"):
        raise ValueError("Unknown Excel sheet")
    # A blank MC lead time is a review requirement, not zero days.
    return dict(excel_baseline=True, lead_time=terms["lead_days"],
                minimum_stock=terms["minimum"], maximum_stock=terms["maximum"])


def _admin():
    import frappe
    if frappe.session.user != "Administrator" or getattr(frappe.local, "request", None):
        frappe.throw("Administrator console required")


def _mapping_snapshot(change, lock=False):
    import frappe
    from qcmc_logic.dynamic_reorder_service import load_mapping
    from qcmc_logic.dynamic_reorder_policy import mapping_warehouses, active_on
    from qcmc_logic.dynamic_reorder_clock import business_date
    from qcmc_logic.dynamic_reorder_transfer import validate_transfer_source
    today = business_date()
    mapping, policy = load_mapping(change["company"], change["mapping"], today)
    if lock:
        policy = frappe.get_doc("Reorder Policy", policy.name, for_update=True)
    warehouses = sorted(mapping_warehouses(mapping))
    if (not active_on(mapping, today) or not policy.enabled or policy.inventory_category != "FG"
            or policy.inventory_type != change["inventory_type"]
            or set(warehouses) != expected_scope(change["warehouse"])
            or mapping.replenishment_warehouse != change["warehouse"]
            or mapping.get("automatic_draft_replenishment")
            or policy.material_request_type not in ("Preserve", change["request_type"])):
        frappe.throw("Unsafe baseline mapping: " + mapping.name)
    source = mapping.get("transfer_source_warehouse") or None
    if change["request_type"] == "Transfer":
        if policy.material_request_type != "Preserve":
            frappe.throw("Transfer requires Preserve policy")
        validate_transfer_source(change["company"], source, change["warehouse"], warehouses, read_only=not lock)
    return dict(policy=policy.name, warehouses=warehouses, transfer_source_warehouse=source,
        policy_snapshot={field:policy.get(field) for field in POLICY_FIELDS})


def preview():
    import frappe
    from qcmc_logic.dynamic_reorder_adoption import adoption_preview, _require_disabled
    _admin()
    _require_disabled()
    plan = adoption_preview()
    entries = read_workbook(Path(frappe.get_site_path("private", "files", FILENAME)).read_bytes())
    reconcile(plan, entries, frappe.get_all("Item", pluck="name"))
    snapshots = {}
    changes = []
    for change in plan["changes"]:
        name = change["mapping"]
        if name not in snapshots:
            snapshots[name] = _mapping_snapshot(change)
        changes.append(dict(change, terms=entries[key(change["item"], change["warehouse"])],
                            snapshot=snapshots[name]))
    payload = dict(adoption_digest=plan["digest"], workbook_sha256=CHECKSUM,
        changes=changes, exclusions=plan["exclusions"])
    return dict(payload, digest=digest(payload), count=len(changes), ready=True,
                qc_count=sum(c["terms"]["sheet"] == "QC" for c in changes),
                mc_count=sum(c["terms"]["sheet"] == "MC" for c in changes),
                missing_lead_time=sum(c["terms"]["lead_days"] is None for c in changes))


def approve(expected_digest=None, apply=False):
    """Approve the immutable reviewed workbook, atomically with ownership adoption."""
    import frappe
    from frappe.utils import now_datetime
    from qcmc_logic.dynamic_reorder_adoption import adopt_existing, _require_disabled
    from qcmc_logic.dynamic_reorder_clock import business_date
    from qcmc_logic.dynamic_reorder_audit import record
    _admin()
    plan = preview()
    if not apply:
        return plan
    if not expected_digest or expected_digest != plan["digest"]:
        frappe.throw("Reviewed Excel approval digest required")
    frappe.db.savepoint("qcmc_excel_baseline")
    try:
        adopt_existing(plan["adoption_digest"], apply=True)
        checked = {}
        for change in plan["changes"]:
            mapping = change["mapping"]
            if mapping not in checked:
                checked[mapping] = _mapping_snapshot(change, lock=True)
            if digest(checked[mapping]) != digest(change["snapshot"]):
                frappe.throw("Mapping changed after baseline preview")
            current = frappe.db.get_value("Item Reorder", change["row"],
                ["parent", "warehouse", "warehouse_group", "material_request_type",
                 "warehouse_reorder_level", "warehouse_reorder_qty", "custom_managed_reorder",
                 "custom_reorder_mapping", "custom_reorder_history"], as_dict=True, for_update=True)
            if (not current or current.parent != change["item"]
                    or current.warehouse != change["warehouse"] or current.warehouse_group != current.warehouse
                    or current.material_request_type != change["request_type"]
                    or not current.custom_managed_reorder or current.custom_reorder_mapping != mapping
                    or current.custom_reorder_history
                    or Decimal(str(current.warehouse_reorder_level)) != Decimal(change["terms"]["level"])
                    or Decimal(str(current.warehouse_reorder_qty)) != Decimal(change["terms"]["qty"])):
                frappe.throw("Adopted row changed: " + change["row"])
            if frappe.db.exists("Item Reorder Override", {"mapping":mapping,"item_code":change["item"],"enabled":1}):
                frappe.throw("Active item override requires separate review")
            terms = change["terms"]
            row = dict(schema_version=2, production_mode="Make to Stock", approval_source="Excel Baseline",
                workbook_sha256=CHECKSUM, approval_digest=expected_digest, excel_terms=terms,
                company=change["company"], item_code=change["item"], mapping=mapping,
                warehouse=change["warehouse"], reorder_row=change["row"], status="Approved",
                previous_level=terms["level"], previous_qty=terms["qty"], reorder_level=terms["level"],
                reorder_qty=terms["qty"], previous_history=None, applied_request_type=change["request_type"],
                material_request_type=change["request_type"], reason="Approved exact Excel baseline; no recalculation",
                **checked[mapping])
            history = record(row, "EXCEL-" + CHECKSUM, business_date())
            h = frappe.get_doc("Reorder Calculation History", history)
            if (h.status != "Approved" or h.reorder_row != change["row"]
                    or h.applied_at or frappe.parse_json(h.details).get("approval_digest") != expected_digest
                    or any(Decimal(str(h.get(field))) != Decimal(terms[value]) for field,value in (
                        ("previous_level", "level"), ("previous_qty", "qty"),
                        ("recommended_level", "level"), ("recommended_qty", "qty")))):
                frappe.throw("Existing history requires separate review")
            frappe.db.set_value("Reorder Calculation History", history,
                dict(applied_by=frappe.session.user, applied_at=now_datetime(), created_reorder_row=0))
            frappe.db.set_value("Item Reorder", change["row"], "custom_reorder_history", history)
        _require_disabled()
    except Exception:
        frappe.db.rollback(save_point="qcmc_excel_baseline")
        raise
    return dict(status="Approved - Not Committed", count=plan["count"], digest=expected_digest,
                excluded=len(plan["exclusions"]))
