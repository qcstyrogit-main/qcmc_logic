"""Configurable demand in stock UOM from submitted, non-cancelled ledger movements."""
from datetime import date
from decimal import Decimal
import frappe
from qcmc_logic.dynamic_reorder_calculation import number

DEMAND_SOURCES = ("Delivery Note", "Material Transfer for Manufacture",
                  "Intercompany Warehouse Transfer", "Provincial Warehouse Transfer")
SOURCE_FIELDS = dict(zip(DEMAND_SOURCES, ("demand_delivery", "demand_manufacture",
                                         "demand_intercompany", "demand_provincial")))


def configured_sources(policy):
    return tuple(source for source, field in SOURCE_FIELDS.items() if policy.get(field))


def aggregate_movements(events, warehouses, sources, deduct_returns=True):
    """Normalize qualifying issues and explicit returns; inbound supply is never a return.

    SQL selects the authoritative representation for legacy linked transfers.
    Duplicate join rows with the same SLE identity are additionally suppressed here.
    """
    scope, enabled, seen, result = set(warehouses), set(sources), set(), {}
    for row in events:
        if (row.get("id") in seen or row.get("docstatus") != 1 or row.get("is_cancelled") or
                row.get("warehouse") not in scope or row.get("source_type") not in enabled):
            continue
        seen.add(row["id"])
        if row.get("source") in scope and row.get("target") in scope:
            continue
        qty = number(row["actual_qty"])
        gross = -qty if qty < 0 and not row.get("is_return") else Decimal(0)
        returns = qty if qty > 0 and row.get("is_return") else Decimal(0)
        if not gross and not returns:
            continue
        day = date.fromisoformat(str(row["posting_date"]))
        key = row["item_code"], row["warehouse"], day.replace(day=1)
        entry = result.setdefault(key, dict(gross=Decimal(0), returns=Decimal(0), net=Decimal(0)))
        entry["gross"] += gross
        entry["returns"] += returns
        entry["net"] += gross - returns if deduct_returns else gross
    return result


def monthly_demand(company, warehouses, items, start, end, deduct_returns=True, sources=None):
    if not warehouses or not items:
        return {}
    sources = DEMAND_SOURCES if sources is None else tuple(sources)
    if not sources:
        return {}
    params = (company, tuple(warehouses), tuple(items), start, end)
    bounds = """s.company=%s AND s.warehouse IN %s AND s.item_code IN %s
                AND s.posting_date BETWEEN %s AND %s AND s.is_cancelled=0"""
    columns = """s.name id, s.item_code, s.warehouse, s.posting_date, s.actual_qty,
                 s.is_cancelled, v.docstatus"""
    events = []
    if "Delivery Note" in sources:
        internal = " AND COALESCE(v.is_internal_customer,0)=0" if frappe.get_meta("Delivery Note").has_field("is_internal_customer") else ""
        events.extend(frappe.db.sql(f"""
            SELECT {columns}, v.is_return, 'Delivery Note' source_type,
                   CASE WHEN v.is_return=0 THEN s.warehouse ELSE NULL END source,
                   CASE WHEN v.is_return=1 THEN s.warehouse ELSE NULL END target
            FROM `tabStock Ledger Entry` s JOIN `tabDelivery Note` v ON v.name=s.voucher_no
            WHERE s.voucher_type='Delivery Note' AND v.docstatus=1 AND {bounds} {internal}
        """, params, as_dict=True))
    has_transfer = bool(frappe.db.exists("DocType", "Warehouse Transfer"))
    transfer_join, transfer_type, exclusion = "", "v.stock_entry_type", ""
    source, target = "d.s_warehouse", "d.t_warehouse"
    if has_transfer:
        transfer_join = "LEFT JOIN `tabWarehouse Transfer` wt ON v.name IN (wt.source_stock_entry,wt.target_stock_entry)"
        transfer_type = "COALESCE(wt.transfer_type,v.stock_entry_type)"
        source = "COALESCE(NULLIF(d.s_warehouse,''),wt.source_warehouse)"
        target = "COALESCE(NULLIF(d.t_warehouse,''),wt.target_warehouse)"
        # The direct ledger is authoritative if both posting models exist. Match the
        # item, warehouse and direction, across all dates (not merely this period).
        exclusion = """AND (wt.name IS NULL OR (wt.docstatus=1 AND NOT EXISTS (
            SELECT direct.name FROM `tabStock Ledger Entry` direct
            WHERE direct.voucher_type='Warehouse Transfer' AND direct.voucher_no=wt.name
              AND direct.item_code=s.item_code AND direct.warehouse=s.warehouse
              AND direct.is_cancelled=0 AND SIGN(direct.actual_qty)=SIGN(s.actual_qty))))"""
    if any(s in sources for s in DEMAND_SOURCES[1:]):
        events.extend(frappe.db.sql(f"""
            SELECT {columns}, v.is_return, {source} source, {target} target,
                CASE WHEN {transfer_type} IN ('Intercompany Warehouse Transfer','Provincial Warehouse Transfer')
                     THEN {transfer_type} ELSE v.purpose END source_type
            FROM `tabStock Ledger Entry` s JOIN `tabStock Entry` v ON v.name=s.voucher_no
            JOIN `tabStock Entry Detail` d ON d.name=s.voucher_detail_no AND d.parent=v.name
            {transfer_join}
            WHERE s.voucher_type='Stock Entry' AND v.docstatus=1 AND {bounds} {exclusion}
              AND (v.purpose='Material Transfer for Manufacture' OR
                   {transfer_type} IN ('Intercompany Warehouse Transfer','Provincial Warehouse Transfer'))
        """, params, as_dict=True))
    if has_transfer and any(s in sources for s in DEMAND_SOURCES[2:]):
        # Current WT has no return flag. Optional explicit return metadata is
        # honored when present; reverse transfers alone cannot prove a return.
        return_flag = "v.is_return" if frappe.get_meta("Warehouse Transfer").has_field("is_return") else "0"
        events.extend(frappe.db.sql(f"""
            SELECT {columns}, {return_flag} is_return, v.transfer_type source_type,
                   v.source_warehouse source, v.target_warehouse target
            FROM `tabStock Ledger Entry` s JOIN `tabWarehouse Transfer` v ON v.name=s.voucher_no
            WHERE s.voucher_type='Warehouse Transfer' AND v.docstatus=1 AND {bounds}
              AND v.transfer_type IN ('Intercompany Warehouse Transfer','Provincial Warehouse Transfer')
        """, params, as_dict=True))
    return aggregate_movements(events, warehouses, sources, deduct_returns)
