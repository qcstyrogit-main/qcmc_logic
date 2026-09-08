import frappe
from frappe import _
from frappe.utils import escape_html, flt, get_url_to_form


@frappe.whitelist()
def get_sales_order_delivery_warning(delivery_note):
    if isinstance(delivery_note, str):
        delivery_note = frappe.parse_json(delivery_note)
    delivery_note = frappe._dict(delivery_note or {})
    permission_type = (
        "create"
        if delivery_note.get("__islocal") or not delivery_note.get("name")
        else "write"
    )
    if not frappe.has_permission("Delivery Note", permission_type):
        frappe.throw(_("Not permitted to save Delivery Note"), frappe.PermissionError)

    current_items = _get_current_sales_order_items(delivery_note)
    if not current_items:
        return {"has_warning": False, "message": ""}

    sales_order_items = frappe.get_all(
        "Sales Order Item",
        filters={"name": ["in", list(current_items)]},
        fields=["name", "parent", "item_code", "stock_qty"],
    )
    sales_order_by_detail = {row.name: row for row in sales_order_items}
    existing_rows = frappe.db.sql(
        """
        select dni.so_detail, dni.parent as delivery_note, dn.docstatus,
            sum(ifnull(dni.stock_qty, 0)) as delivered_stock_qty
        from `tabDelivery Note Item` dni
        inner join `tabDelivery Note` dn on dn.name = dni.parent
        where dn.docstatus in (0, 1)
            and ifnull(dn.is_return, 0) = 0
            and dn.name != %(current_delivery_note)s
            and dni.so_detail in %(so_details)s
        group by dni.so_detail, dni.parent, dn.docstatus
        order by dn.docstatus, dni.parent
        """,
        {
            "current_delivery_note": delivery_note.get("name") or "",
            "so_details": tuple(current_items),
        },
        as_dict=True,
    )
    existing_by_detail = {}
    for row in existing_rows:
        existing_by_detail.setdefault(row.so_detail, []).append(row)

    warnings = []
    for so_detail, current_qty in current_items.items():
        so_item = sales_order_by_detail.get(so_detail)
        if not so_item:
            continue
        existing = existing_by_detail.get(so_detail, [])
        existing_qty = sum(flt(row.delivered_stock_qty) for row in existing)
        total_qty = existing_qty + current_qty
        if existing or total_qty > flt(so_item.stock_qty):
            warnings.append(
                frappe._dict(
                    sales_order=so_item.parent,
                    item_code=so_item.item_code,
                    ordered_qty=flt(so_item.stock_qty),
                    existing_qty=existing_qty,
                    current_qty=current_qty,
                    total_qty=total_qty,
                    is_over_delivery=total_qty > flt(so_item.stock_qty),
                    delivery_notes=existing,
                )
            )

    return {
        "has_warning": bool(warnings),
        "message": _build_warning_message(warnings) if warnings else "",
    }


def _get_current_sales_order_items(delivery_note):
    quantities = {}
    for item in delivery_note.get("items") or []:
        item = frappe._dict(item)
        sales_order = item.get("against_sales_order") or item.get("sales_order")
        if not sales_order or not item.get("so_detail"):
            continue
        stock_qty = item.get("stock_qty")
        if stock_qty is None:
            stock_qty = flt(item.get("qty")) * flt(item.get("conversion_factor") or 1)
        quantities[item.so_detail] = quantities.get(item.so_detail, 0) + flt(stock_qty)
    return quantities

def _build_warning_message(warnings):
    cards = []
    for warning in warnings:
        delivery_notes = "".join(
            "<li style=\"margin: 4px 0;\">{0} <span class=\"text-muted\">({1})</span></li>".format(
                _document_link("Delivery Note", row.delivery_note),
                _("Submitted") if row.docstatus == 1 else _("Draft"),
            )
            for row in warning.delivery_notes
        ) or "<li>{0}</li>".format(_("None"))
        status = (
            _("Exceeds the Sales Order quantity")
            if warning.is_over_delivery
            else _("Another Delivery Note already exists")
        )
        status_color = "#b42318" if warning.is_over_delivery else "#9a6700"
        cards.append(
            """
            <div style="border: 1px solid var(--border-color); border-radius: 8px; padding: 12px; margin: 12px 0;">
                <div style="display: flex; justify-content: space-between; gap: 12px; flex-wrap: wrap; margin-bottom: 10px;">
                    <div><div class="text-muted">{sales_order_label}</div>{sales_order}</div>
                    <div><div class="text-muted">{item_label}</div><strong>{item_code}</strong></div>
                </div>
                <div style="display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; margin-bottom: 10px;">
                    <div style="background: var(--subtle-fg); padding: 8px; border-radius: 6px;"><div class="text-muted">{ordered_label}</div><strong>{ordered_qty}</strong></div>
                    <div style="background: var(--subtle-fg); padding: 8px; border-radius: 6px;"><div class="text-muted">{existing_label}</div><strong>{existing_qty}</strong></div>
                    <div style="background: var(--subtle-fg); padding: 8px; border-radius: 6px;"><div class="text-muted">{current_label}</div><strong>{current_qty}</strong></div>
                    <div style="background: var(--subtle-fg); padding: 8px; border-radius: 6px;"><div class="text-muted">{total_label}</div><strong>{total_qty}</strong></div>
                </div>
                <div style="color: {status_color}; font-weight: 600; margin-bottom: 8px;">{status}</div>
                <div class="text-muted">{delivery_notes_label}</div>
                <ul style="margin: 4px 0 0; padding-left: 20px;">{delivery_notes}</ul>
            </div>
            """.format(
                sales_order_label=_("Sales Order"),
                sales_order=_document_link("Sales Order", warning.sales_order),
                item_label=_("Item"),
                item_code=escape_html(warning.item_code),
                ordered_label=_("Ordered Qty"),
                ordered_qty=warning.ordered_qty,
                existing_label=_("Existing DN Qty"),
                existing_qty=warning.existing_qty,
                current_label=_("Current DN Qty"),
                current_qty=warning.current_qty,
                total_label=_("Total DN Qty"),
                total_qty=warning.total_qty,
                status_color=status_color,
                status=status,
                delivery_notes_label=_("Existing Delivery Notes"),
                delivery_notes=delivery_notes,
            )
        )

    return """
        <p>{intro}</p>
        {cards}
        <p style="margin-top: 14px;"><strong>{question}</strong></p>
    """.format(
        intro=_("Please review the existing deliveries before continuing."),
        cards="".join(cards),
        question=_("Do you understand the warning and want to continue saving?"),
    )


def _document_link(doctype, name):
    return '<a href="{0}" style="font-weight: bold;">{1}</a>'.format(
        get_url_to_form(doctype, name),
        escape_html(name),
    )
