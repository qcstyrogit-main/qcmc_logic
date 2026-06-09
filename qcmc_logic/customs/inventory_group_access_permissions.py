import frappe


TRANSACTION_DOCTYPES = {
    "Delivery Note",
    "Material Request",
    "Pick List",
    "Purchase Invoice",
    "Purchase Order",
    "Purchase Receipt",
    "Sales Invoice",
    "Stock Entry",
    "Stock Reconciliation",
    "Warehouse Transfer",
}

SKIP_DOCTYPES = {
    "Allowed Inventory Group",
    "Error Log",
    "Inventory Group",
    "Inventory Group Access",
    "Item",
    "Role Profile Inventory Group Access",
}


def validate_inventory_group_access(doc, method=None):
    if (
        frappe.session.user == "Administrator"
        or doc.doctype in SKIP_DOCTYPES
        or doc.doctype not in TRANSACTION_DOCTYPES
    ):
        return

    from qcmc_logic.utils import (
        get_user_allowed_inventory_groups,
        has_inventory_group_access,
    )

    if not has_inventory_group_access(frappe.session.user):
        return

    allowed_inventory_groups = set(
        get_user_allowed_inventory_groups(
            frappe.session.user,
            require_transact=True,
        )
    )

    for fieldname, item_code, inventory_group in _iter_item_values(doc):
        if not inventory_group:
            frappe.throw(
                "{0} has no Inventory Group set on the Item master.".format(
                    frappe.bold(item_code),
                )
            )

        if inventory_group not in allowed_inventory_groups:
            frappe.throw(
                "{0} belongs to Inventory Group {1}, which you are not allowed to transact.".format(
                    frappe.bold(item_code),
                    frappe.bold(inventory_group),
                )
            )


def _iter_item_values(doc):
    for df in doc.meta.fields:
        if df.fieldtype == "Link" and df.options == "Item":
            item_code = doc.get(df.fieldname)
            if item_code:
                yield (
                    df.fieldname,
                    item_code,
                    _get_item_inventory_group(item_code),
                )

        if df.fieldtype != "Table" or not df.options:
            continue

        child_meta = frappe.get_meta(df.options)
        item_fields = [
            child_df
            for child_df in child_meta.fields
            if child_df.fieldtype == "Link" and child_df.options == "Item"
        ]
        if not item_fields:
            continue

        for row in doc.get(df.fieldname) or []:
            for child_df in item_fields:
                item_code = row.get(child_df.fieldname)
                if item_code:
                    yield (
                        child_df.fieldname,
                        item_code,
                        _get_item_inventory_group(item_code),
                    )


def _get_item_inventory_group(item_code):
    return frappe.db.get_value("Item", item_code, "custom_inventory_group")
