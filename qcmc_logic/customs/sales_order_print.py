from collections import OrderedDict

import frappe
from frappe.utils import flt


def get_sales_order_slip_items(doc):
    groups = OrderedDict()

    for item in doc.get("items") or []:
        key = (
            item.get("item_code"),
            item.get("item_name"),
            item.get("uom"),
            flt(item.get("rate")),
        )
        delivery_date = item.get("delivery_date") or item.get("schedule_date") or ""

        if key not in groups:
            groups[key] = frappe._dict(
                qty=0,
                uom=item.get("uom"),
                item_code=item.get("item_code"),
                item_name=item.get("item_name"),
                rate=flt(item.get("rate")),
                amount=0,
                lines=[],
            )

        group = groups[key]
        qty = flt(item.get("qty"))
        amount = flt(item.get("amount"))
        group.qty += qty
        group.amount += amount
        group.lines.append(
            frappe._dict(
                qty=qty,
                uom=item.get("uom"),
                item_code=item.get("item_code"),
                item_name=item.get("item_name"),
                rate=flt(item.get("rate")),
                amount=amount,
                delivery_date=delivery_date,
                is_summary=0,
            )
        )

    rows = []
    for group in groups.values():
        rows.extend(group.lines)
        rows.append(
            frappe._dict(
                qty=group.qty,
                uom=group.uom,
                item_code=group.item_code,
                item_name=group.item_name,
                rate=group.rate,
                amount=group.amount,
                delivery_date="",
                is_summary=1,
            )
        )

    return rows
