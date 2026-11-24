"""Finished Goods demand from actual posted stock movements."""
import frappe
from datetime import date
from decimal import Decimal

def monthly_demand(company, warehouses, items, start, end, deduct_returns=True):
    if not warehouses or not items:
        return {}
    # A linked invoice without stock movement has no SLE, so it is not counted.
    # Positive quantities count only on explicitly identified customer returns.
    result = {}
    for voucher in ("Delivery Note", "Sales Invoice", "POS Invoice"):
        if not frappe.db.exists("DocType", voucher):
            continue
        # Identifiers are fixed constants, never user supplied.
        extra = ""
        if frappe.get_meta(voucher).has_field("is_internal_customer"):
            extra += " AND COALESCE(v.is_internal_customer,0)=0"
        if frappe.get_meta(voucher).has_field("update_stock"):
            extra += " AND v.update_stock=1"
        rows = frappe.db.sql(f"""
            SELECT s.item_code, s.warehouse, YEAR(s.posting_date) yr,
                   MONTH(s.posting_date) mo,
                   SUM(CASE WHEN s.actual_qty < 0 AND COALESCE(v.is_return,0)=0
                            THEN -s.actual_qty ELSE 0 END) gross,
                   SUM(CASE WHEN s.actual_qty > 0 AND v.is_return=1
                            THEN s.actual_qty ELSE 0 END) returns
            FROM `tabStock Ledger Entry` s
            JOIN `tab{voucher}` v ON v.name=s.voucher_no
            WHERE s.voucher_type=%s AND s.company=%s AND v.docstatus=1
              AND s.is_cancelled=0 AND s.warehouse IN %s AND s.item_code IN %s
              AND s.posting_date BETWEEN %s AND %s {extra}
            GROUP BY s.item_code,s.warehouse,YEAR(s.posting_date),MONTH(s.posting_date)
            """, (voucher, company, tuple(warehouses), tuple(items), start, end), as_dict=True)
        for row in rows:
            key = (row.item_code, row.warehouse, date(row.yr, row.mo, 1))
            entry = result.setdefault(key, {"gross": Decimal(0), "returns": Decimal(0), "net": Decimal(0)})
            gross, returns = Decimal(str(row.gross)), Decimal(str(row.returns))
            entry["gross"] += gross
            entry["returns"] += returns
            entry["net"] += gross - returns if deduct_returns else gross
    return result
