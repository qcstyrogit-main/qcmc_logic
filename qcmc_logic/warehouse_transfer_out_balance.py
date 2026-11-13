"""Read-only attribution of posted Warehouse Transfer OUT to picked source locations.

Stock Ledger Entry records the warehouse issue. A linked Pick List records
which Storage Locations supplied it. Do not create additional stock ledger rows.
"""
from collections import defaultdict

import frappe
from frappe.utils import flt


def get_out_movements(warehouse, location=None, item_code=None, after=None):
    """Return posted, non-cancelled WT source issues allocated to picked locations.

    Multiple location rows can represent one Pick List item. Distribute actual
    posted issue quantity in row order, never more than each picked quantity.
    """
    values = {"warehouse": warehouse}
    filters = ["wt.source_warehouse = %(warehouse)s", "wt.docstatus = 1",
               "pl.docstatus = 1", "sle.is_cancelled = 0", "sle.actual_qty < 0"]
    if item_code:
        filters.append("d.item_code = %(item_code)s")
        values["item_code"] = item_code
    # Read all issues before allocating across location rows. Filtering older
    # transfers first could misattribute a later partial issue to the first bin.
    issued = frappe.db.sql(
        """
        select wt.name as transfer, wt.source_warehouse, wt.target_warehouse, d.item_code,
               coalesce(d.material_request_item, '') as request_item,
               d.against_pick_list as pick_list, d.name as transfer_item,
               sle.actual_qty, sle.posting_datetime as movement_time,
               sle.stock_uom as uom, sle.location as ledger_location,
               coalesce(sle.owner, wt.owner) as performed_by
        from `tabWarehouse Transfer Details` d
        inner join `tabWarehouse Transfer` wt on wt.name = d.parent
        inner join `tabPick List` pl on pl.name = d.against_pick_list
        inner join `tabStock Ledger Entry` sle
          on sle.voucher_type = 'Warehouse Transfer' and sle.voucher_no = wt.name
          and sle.voucher_detail_no = d.name
        where """ + " and ".join(filters) + """
        order by sle.posting_datetime, wt.name, d.idx, sle.name
        """, values, as_dict=True,
    )
    if not issued:
        return []

    pick_names = sorted({row.pick_list for row in issued})
    pick_rows = frappe.db.sql(
        """
        select parent, item_code, warehouse, coalesce(material_request_item, '') as request_item,
               name, location, picked_qty, idx
        from `tabPick List Item`
        where parent in %(pick_names)s and warehouse = %(warehouse)s
        order by parent, item_code, idx, name
        """, {"pick_names": tuple(pick_names), "warehouse": warehouse}, as_dict=True,
    )
    available = defaultdict(list)
    for row in pick_rows:
        if row.location and flt(row.picked_qty) > 0:
            key = (row.parent, row.item_code, row.request_item)
            available[key].append([row.location, flt(row.picked_qty)])

    results = []
    for issue in issued:
        remaining = abs(flt(issue.actual_qty))
        key = (issue.pick_list, issue.item_code, issue.request_item)
        for candidate in available[key]:
            if remaining <= 1e-9:
                break
            take = min(remaining, candidate[1])
            if take <= 0:
                continue
            candidate[1] -= take
            remaining -= take
            if (location is None or candidate[0] == location) and (
                after is None or issue.movement_time > after
            ):
                results.append({
                    "item_code": issue.item_code,
                    "location": candidate[0],
                    "quantity": -take,
                    "uom": issue.uom,
                    "reference_name": issue.transfer,
                    "movement_time": issue.movement_time,
                    "performed_by": issue.performed_by,
                    "ledger_location": issue.ledger_location,
                    "target_warehouse": issue.target_warehouse,
                })
    return results


def get_out_quantity(warehouse, location, item_code, after=None):
    return sum(flt(row["quantity"]) for row in get_out_movements(
        warehouse, location=location, item_code=item_code, after=after
    ))
