"""Read-only location attribution for submitted Stock Entry material transfers.

Stock Ledger Entries are authoritative for *actual* outbound quantities, while
submitted Pick List location rows identify which storage bins supplied them.
Do not infer an OUT from a draft Pick List or an unposted Stock Entry.
"""
from collections import defaultdict

import frappe
from frappe.utils import flt


def get_out_movements(warehouse, location=None, item_code=None, after=None):
    filters = [
        "se.docstatus = 1", "pl.docstatus = 1",
        "se.purpose in ('Material Transfer for Manufacture', 'Material Issue')",
        "pl.purpose = se.purpose",
        "sle.voucher_type = 'Stock Entry'", "sle.is_cancelled = 0",
        "sle.actual_qty < 0", "sle.warehouse = %(warehouse)s",
    ]
    params = {"warehouse": warehouse}
    if item_code:
        filters.append("sle.item_code = %(item_code)s")
        params["item_code"] = item_code

    issues = frappe.db.sql("""
        select se.name as stock_entry, se.pick_list, sle.name as ledger_entry,
               sle.item_code, sle.actual_qty, sle.stock_uom as uom,
               sle.posting_datetime as movement_time, sle.location as ledger_location,
               coalesce(sle.owner, se.owner) as performed_by,
               coalesce(se.to_warehouse, '') as target_warehouse,
               se.purpose as stock_entry_purpose
        from `tabStock Ledger Entry` sle
        inner join `tabStock Entry` se on se.name = sle.voucher_no
        inner join `tabPick List` pl on pl.name = se.pick_list
        where """ + " and ".join(filters) + """
        order by sle.posting_datetime, se.name, sle.item_code, sle.name
    """, params, as_dict=True)
    picks = []
    if issues:
        pick_names = tuple(sorted({row.pick_list for row in issues}))
        picks = frappe.db.sql("""
            select parent, item_code, warehouse, location, picked_qty, idx, name
            from `tabPick List Item`
            where parent in %(parents)s and warehouse = %(warehouse)s
            order by parent, item_code, idx, name
        """, {"parents": pick_names, "warehouse": warehouse}, as_dict=True)
    available = defaultdict(list)
    for row in picks:
        if row.location and flt(row.picked_qty) > 0:
            available[(row.parent, row.item_code)].append(
                [row.location, flt(row.picked_qty)])
    results = []
    for issue in issues:
        remaining = abs(flt(issue.actual_qty))
        for candidate in available[(issue.pick_list, issue.item_code)]:
            if remaining <= 1e-9:
                break
            taken = min(remaining, candidate[1])
            if taken <= 0:
                continue
            candidate[1] -= taken
            remaining -= taken
            if (location is None or candidate[0] == location) and (
                after is None or issue.movement_time > after
            ):
                results.append({
                    "item_code": issue.item_code,
                    "location": candidate[0],
                    "quantity": -taken,
                    "uom": issue.uom,
                    "reference_name": issue.stock_entry,
                    "pick_list": issue.pick_list,
                    "movement_time": issue.movement_time,
                    "performed_by": issue.performed_by,
                    "ledger_location": issue.ledger_location,
                    "target_warehouse": issue.target_warehouse,
                    "purpose": issue.stock_entry_purpose,
                })
    # Legacy submitted Material Issues can be explicitly attributed by an
    # authorized user to a physical bin, with an audit comment. Never guess
    # a bin from the warehouse or from its remaining balance.
    direct = frappe.db.sql("""
        select se.name as stock_entry, sed.item_code,
               sed.custom_actual_storage_location as location,
               sle.actual_qty, sle.stock_uom as uom,
               sle.posting_datetime as movement_time,
               sle.location as ledger_location,
               coalesce(sle.owner, se.owner) as performed_by
        from `tabStock Ledger Entry` sle
        inner join `tabStock Entry` se on se.name = sle.voucher_no
        inner join `tabStock Entry Detail` sed
            on sed.name = sle.voucher_detail_no and sed.parent = se.name
        where se.docstatus = 1 and se.purpose = 'Material Issue'
            and coalesce(se.pick_list, '') = ''
            and sle.voucher_type = 'Stock Entry' and sle.is_cancelled = 0
            and sle.actual_qty < 0 and sle.warehouse = %(warehouse)s
            and sed.s_warehouse = %(warehouse)s
            and coalesce(sed.custom_actual_storage_location, '') != ''
            """ + (" and sle.item_code = %(item_code)s" if item_code else "") + """
        order by sle.posting_datetime, se.name, sle.name
    """, params, as_dict=True)
    for issue in direct:
        if location is not None and issue.location != location:
            continue
        if after is not None and issue.movement_time <= after:
            continue
        results.append({
            "item_code": issue.item_code,
            "location": issue.location,
            "quantity": flt(issue.actual_qty),
            "uom": issue.uom,
            "reference_name": issue.stock_entry,
            "pick_list": "",
            "movement_time": issue.movement_time,
            "performed_by": issue.performed_by,
            "ledger_location": issue.ledger_location,
            "target_warehouse": "",
            "purpose": "Material Issue",
        })
    return results
