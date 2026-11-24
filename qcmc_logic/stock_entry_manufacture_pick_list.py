"""Pick List creation from a saved draft manufacturing Stock Entry.

Uses the existing Stock Entry.pick_list field; does not create or post stock.
"""
import frappe
from frappe import _
from frappe.utils import flt
from qcmc_logic.warehouse_transfer_allocation import warehouse_has_storage_locations


def requires_source_picking(doc):
    return any(flt(row.qty) > 0 and warehouse_has_storage_locations(row.s_warehouse)
               for row in (doc.get('items') or []))


def validate_manufacturing_transfer_pick_list(doc, method=None):
    """Validate the actual picked source quantities before manufacturing transfer."""
    if (doc.stock_entry_type != "Material Transfer for Manufacture"
            or doc.purpose != "Material Transfer for Manufacture"):
        return
    if not doc.pick_list and not requires_source_picking(doc):
        return
    if not doc.pick_list:
        frappe.throw(_("Create and submit a Pick List before transferring manufacturing materials."))
    pick = frappe.get_doc("Pick List", doc.pick_list)
    if (pick.docstatus != 1 or pick.purpose != "Material Transfer for Manufacture"
            or pick.company != doc.company or pick.work_order != doc.work_order):
        frappe.throw(_("A submitted Pick List for the same company and Work Order is required."))

    from collections import defaultdict
    expected, picked = defaultdict(float), defaultdict(float)
    linked_keys = {(row.item_code, row.warehouse) for row in pick.locations}
    for row in doc.items:
        if flt(row.qty) > 0 and (warehouse_has_storage_locations(row.s_warehouse) or (row.item_code, row.s_warehouse) in linked_keys):
            expected[(row.item_code, row.s_warehouse)] += flt(
                row.transfer_qty or flt(row.qty) * flt(row.conversion_factor or 1))
    if not expected:
        frappe.throw(_("Add material items before transferring."))
    for row in pick.locations:
        if flt(row.picked_qty) <= 0 or (warehouse_has_storage_locations(row.warehouse) and not row.location):
            frappe.throw(_("All Pick List rows must have a source Storage Location and positive picked quantity."))
        if row.location and frappe.db.get_value("Storage Location", row.location, "custom_warehouse") != row.warehouse:
            frappe.throw(_("Pick List location {0} does not belong to warehouse {1}.").format(row.location, row.warehouse))
        picked[(row.item_code, row.warehouse)] += flt(row.picked_qty)
    if set(expected) != set(picked) or any(abs(expected[key] - picked[key]) > 1e-6 for key in expected):
        frappe.throw(_("Manufacturing Pick List items, warehouses and picked quantities must match the Stock Entry."))


@frappe.whitelist()
def get_manufacturing_transfer_action_state(stock_entry):
    entry = frappe.get_doc("Stock Entry", stock_entry)
    entry.check_permission("read")
    if (entry.stock_entry_type != "Material Transfer for Manufacture"
            or entry.purpose != "Material Transfer for Manufacture"):
        return {"managed": False}
    if entry.docstatus != 0:
        return {"managed": True, "stage": "submitted"}
    if not any(flt(row.qty) > 0 for row in entry.items):
        return {"managed": True, "stage": "empty"}
    if not entry.pick_list and not requires_source_picking(entry):
        return {"managed": True, "stage": "submit"}
    if not entry.pick_list or not frappe.db.exists("Pick List", {
        "name": entry.pick_list, "docstatus": ["!=", 2]}):
        return {"managed": True, "stage": "pick"}
    try:
        validate_manufacturing_transfer_pick_list(entry)
    except (frappe.ValidationError, frappe.DoesNotExistError):
        return {"managed": True, "stage": "pending"}
    return {"managed": True, "stage": "submit"}


@frappe.whitelist(methods=["POST"])
def create_pick_list_from_stock_entry(stock_entry):
    entry = frappe.get_doc("Stock Entry", stock_entry)
    entry.check_permission("write")
    frappe.has_permission("Pick List", "create", throw=True)
    if entry.docstatus != 0 or entry.stock_entry_type != "Material Transfer for Manufacture" or entry.purpose != "Material Transfer for Manufacture":
        frappe.throw(_("Only draft Material Transfer for Manufacture Stock Entries can create a Pick List."))
    if not entry.work_order:
        frappe.throw(_("Select a Work Order before creating a manufacturing Pick List. Use Get Items From → Job Card to populate the materials."))
    if flt(entry.fg_completed_qty) <= 0:
        frappe.throw(_("Enter a positive Qty to Manufacture before creating the Pick List."))
    work_order = frappe.get_doc("Work Order", entry.work_order)
    if work_order.docstatus != 1 or work_order.company != entry.company:
        frappe.throw(_("The Work Order must be submitted and belong to the Stock Entry company."))

    # Reuse an existing link rather than producing a duplicate pick.
    if entry.pick_list:
        linked = frappe.db.get_value("Pick List", entry.pick_list, ["docstatus", "purpose", "work_order"], as_dict=True)
        if linked and linked.docstatus != 2:
            if linked.purpose != "Material Transfer for Manufacture" or linked.work_order != entry.work_order:
                frappe.throw(_("The linked Pick List does not belong to this manufacturing transfer."))
            return {"name": entry.pick_list, "existing": True}
        # Stale/cancelled reference is replaced only for this draft.
        entry.pick_list = None

    rows = [row for row in entry.items if flt(row.qty) > 0 and warehouse_has_storage_locations(row.s_warehouse)]
    if not rows:
        frappe.throw(_("Add materials with positive quantities before creating the Pick List."))
    if any(not row.item_code or not row.s_warehouse for row in rows):
        frappe.throw(_("Each material must have an Item and Source Warehouse."))
    for row in rows:
        if frappe.get_cached_value("Warehouse", row.s_warehouse, "company") != entry.company:
            frappe.throw(_("Source Warehouse {0} does not belong to this company.").format(row.s_warehouse))

    pick = frappe.new_doc("Pick List")
    pick.company = entry.company
    pick.purpose = "Material Transfer for Manufacture"
    pick.work_order = entry.work_order
    pick.for_qty = entry.fg_completed_qty
    pick.pick_manually = 1
    source_warehouses = {row.s_warehouse for row in rows}
    if len(source_warehouses) == 1:
        pick.parent_warehouse = next(iter(source_warehouses))
    for row in rows:
        factor = flt(row.conversion_factor) or 1
        stock_uom = row.stock_uom or frappe.get_cached_value("Item", row.item_code, "stock_uom")
        pick.append("locations", {
            "item_code": row.item_code,
            "warehouse": row.s_warehouse,
            "qty": flt(row.qty),
            "stock_qty": flt(row.qty) * factor,
            "picked_qty": 0,
            "uom": row.uom or stock_uom,
            "stock_uom": stock_uom,
            "conversion_factor": factor,
        })
    pick.insert()
    # Stock Entry already has the native Link field used for Pick List references.
    # Update only that link: all material rows remain untouched.
    frappe.db.set_value("Stock Entry", entry.name, "pick_list", pick.name, update_modified=False)
    from qcmc_logic.picking_status import sync_linked_reference
    sync_linked_reference("Stock Entry", entry.name)
    return {"name": pick.name, "existing": False}
