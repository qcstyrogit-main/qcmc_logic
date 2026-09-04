import frappe


def populate_mapped_transaction_territory(doc, method=None):
    if doc.get("territory"):
        return
    if not doc.meta.has_field("territory"):
        return

    territory = None
    if doc.doctype == "Delivery Note":
        territory = _get_delivery_note_source_territory(doc)
    elif doc.doctype == "Sales Invoice":
        territory = _get_sales_invoice_source_territory(doc)

    if territory:
        doc.territory = territory


def _get_delivery_note_source_territory(doc):
    sales_orders = _get_item_values(doc, "sales_order")
    return _first_value("Sales Order", sales_orders, "territory")


def _get_sales_invoice_source_territory(doc):
    delivery_notes = _get_item_values(doc, "delivery_note")
    territory = _first_value("Delivery Note", delivery_notes, "territory")
    if territory:
        return territory

    sales_orders = _get_item_values(doc, "sales_order")
    return _first_value("Sales Order", sales_orders, "territory")


def _get_item_values(doc, fieldname):
    return [
        row.get(fieldname)
        for row in (doc.get("items") or [])
        if row.get(fieldname)
    ]


def _first_value(doctype, names, fieldname):
    for name in dict.fromkeys(names):
        value = frappe.db.get_value(doctype, name, fieldname)
        if value:
            return value
    return None
