"""Warehouse Transfer native Connections support and safe Pick List linkage."""
import frappe


def ensure_connections_fields():
    """Idempotent custom fields for a custom DocType and its Pick List reference."""
    from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
    # Remove the preliminary tab: native Frappe Connections expects the
    # fieldname "connections_tab", not "custom_connections_tab".
    if frappe.db.exists("Custom Field", "Warehouse Transfer-custom_connections_tab"):
        frappe.delete_doc("Custom Field", "Warehouse Transfer-custom_connections_tab", force=True)
    create_custom_fields({
        "Warehouse Transfer": [{
            "fieldname": "connections_tab",
            "fieldtype": "Tab Break",
            "label": "Connections",
            "insert_after": "custom_shipping_remarks",
            "collapsible": 0,
        }, {
            "fieldname": "custom_pick_list_connections_html",
            "fieldtype": "HTML",
            "label": "Related Pick Lists",
            "insert_after": "connections_tab",
            "read_only": 1,
        }],
        "Pick List": [{
            "fieldname": "custom_warehouse_transfer",
            "fieldtype": "Link",
            "options": "Warehouse Transfer",
            "label": "Warehouse Transfer",
            "insert_after": "amended_from",
            "hidden": 1,
            "read_only": 1,
            "no_copy": 1,
        }],
    }, update=True)
    frappe.clear_cache(doctype="Warehouse Transfer")
    frappe.clear_cache(doctype="Pick List")
    # One source transfer per Pick List; do not infer relationships from
    # unrelated Pick Lists or cancelled documents.
    existing = frappe.db.sql("""
        select d.against_pick_list as pick_list, min(d.parent) as transfer,
               count(distinct d.parent) as transfers
        from `tabWarehouse Transfer Details` d
        inner join `tabPick List` pl on pl.name = d.against_pick_list
        where pl.docstatus != 2 and ifnull(d.against_pick_list, '') != ''
        group by d.against_pick_list
    """, as_dict=True)
    for row in existing:
        if row.transfers != 1:
            continue
        current = frappe.db.get_value("Pick List", row.pick_list, "custom_warehouse_transfer")
        if not current:
            frappe.db.set_value("Pick List", row.pick_list,
                "custom_warehouse_transfer", row.transfer, update_modified=False)


def get_data(data):
    """Add Pick List to native Connections, preserving other cards."""
    data.setdefault("non_standard_fieldnames", {})["Pick List"] = "custom_warehouse_transfer"
    groups = data.setdefault("transactions", [])
    if not any("Pick List" in group.get("items", []) for group in groups):
        groups.append({"label": "Inventory", "items": ["Pick List"]})
    return data
