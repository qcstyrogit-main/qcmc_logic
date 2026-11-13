"""Create a draft picking document from a saved Material Issue Stock Entry.

Only source materials are prepared for picking. No Stock Entry is submitted,
no inventory moves, and existing drafts reuse the same Pick List reference.
"""
import frappe
from frappe import _
from frappe.utils import flt


@frappe.whitelist(methods=["POST"])
def create_pick_list_from_material_issue(stock_entry):
    entry = frappe.get_doc("Stock Entry", stock_entry)
    entry.check_permission("write")
    frappe.has_permission("Pick List", "create", throw=True)
    if (entry.docstatus != 0 or entry.stock_entry_type != "Material Issue"
            or entry.purpose != "Material Issue"):
        frappe.throw(_("Only draft Material Issue Stock Entries can create a Pick List."))

    # Reuse the standard Stock Entry.pick_list link.
    if entry.pick_list:
        linked = frappe.db.get_value(
            "Pick List", entry.pick_list,
            ["docstatus", "purpose", "company"], as_dict=True,
        )
        if linked and linked.docstatus != 2:
            if linked.purpose != "Material Issue" or linked.company != entry.company:
                frappe.throw(_("The linked Pick List does not belong to this Material Issue."))
            return {"name": entry.pick_list, "existing": True}

    rows = [row for row in entry.items if flt(row.qty) > 0]
    if not rows:
        frappe.throw(_("Add items with positive quantities before creating a Pick List."))
    if any(not row.item_code or not row.s_warehouse for row in rows):
        frappe.throw(_("Every material must have an Item and Source Warehouse."))
    for row in rows:
        company = frappe.get_cached_value("Warehouse", row.s_warehouse, "company")
        if not company or company != entry.company:
            frappe.throw(_("Source Warehouse {0} does not belong to the Stock Entry company.").format(row.s_warehouse))

    pick = frappe.new_doc("Pick List")
    pick.company = entry.company
    pick.purpose = "Material Issue"
    pick.pick_manually = 1
    warehouses = {row.s_warehouse for row in rows}
    if len(warehouses) == 1:
        pick.parent_warehouse = next(iter(warehouses))

    for row in rows:
        factor = flt(row.conversion_factor)
        if factor <= 0:
            frappe.throw(_("Invalid conversion factor for Item {0}.").format(row.item_code))
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
    frappe.db.set_value("Stock Entry", entry.name, "pick_list", pick.name, update_modified=False)
    return {"name": pick.name, "existing": False}


def validate_material_issue_picking(doc, method=None):
    """Prevent future location-unattributed Material Issue submissions."""
    if doc.purpose != "Material Issue" or doc.stock_entry_type != "Material Issue":
        return
    if not doc.pick_list:
        frappe.throw(_("Create and submit a Pick List with source Storage Locations before submitting this Material Issue."))
    pick = frappe.get_doc("Pick List", doc.pick_list)
    if pick.docstatus != 1 or pick.purpose != "Material Issue" or pick.company != doc.company:
        frappe.throw(_("The linked Material Issue Pick List must be submitted and belong to this company."))
    from collections import defaultdict
    required = defaultdict(float)
    allocated = defaultdict(float)
    for row in doc.items:
        if flt(row.qty) > 0:
            required[(row.item_code, row.s_warehouse)] += flt(row.transfer_qty or flt(row.qty) * flt(row.conversion_factor or 1))
    for row in pick.locations:
        if not row.location or flt(row.picked_qty) <= 0:
            frappe.throw(_("Every picked item requires a source Storage Location and positive picked quantity."))
        if frappe.db.get_value("Storage Location", row.location, "custom_warehouse") != row.warehouse:
            frappe.throw(_("Pick List location {0} does not belong to warehouse {1}.").format(row.location, row.warehouse))
        allocated[(row.item_code, row.warehouse)] += flt(row.picked_qty)
    for key, qty in required.items():
        if abs(allocated[key] - qty) > 1e-6:
            frappe.throw(_("Pick List quantity for {0} in {1} must match the Stock Entry quantity ({2}).").format(key[0], key[1], qty))
    if set(allocated) != set(required):
        frappe.throw(_("Pick List items and source warehouses must match the Stock Entry."))


@frappe.whitelist(methods=["POST"])
def attribute_submitted_material_issue_source(stock_entry, item_row, storage_location):
    """Audited historical source attribution. Does not create/change stock ledger."""
    entry = frappe.get_doc("Stock Entry", stock_entry)
    entry.check_permission("write")
    if entry.docstatus != 1 or entry.purpose != "Material Issue" or entry.stock_entry_type != "Material Issue":
        frappe.throw(_("Only submitted Material Issue Stock Entries are eligible."))
    if entry.pick_list:
        frappe.throw(_("This Material Issue already has a Pick List; use the linked Pick List locations."))
    row = next((r for r in entry.items if r.name == item_row), None)
    if not row or flt(row.qty) <= 0 or not row.s_warehouse:
        frappe.throw(_("Select a valid issued item row."))
    if row.get("custom_actual_storage_location"):
        frappe.throw(_("This item already has an attributed source location."))
    location = frappe.get_doc("Storage Location", storage_location)
    location.check_permission("read")
    if location.disabled or location.is_group or location.custom_warehouse != row.s_warehouse:
        frappe.throw(_("Select an active leaf Storage Location belonging to the source Warehouse."))
    # Only user-confirmed provenance is stored, never guessed from available stock.
    frappe.db.set_value("Stock Entry Detail", row.name, "custom_actual_storage_location", location.name, update_modified=False)
    entry.add_comment("Comment", _("Historical Material Issue OUT source confirmed: item {0}, quantity {1} {2}, from {3} (row {4}). No Stock Ledger Entry changed.").format(
        row.item_code, flt(row.transfer_qty or row.qty), row.stock_uom or row.uom, location.name, row.name))
    return {"stock_entry": entry.name, "item_row": row.name, "location": location.name}


@frappe.whitelist(methods=["POST"])
def restore_submitted_material_issue_pick_list(stock_entry, pick_list):
    """Reconnect an already submitted issue with its verified original pick.

    Intended for links cleared by old workflows. Does not mutate the posted SLE.
    """
    from collections import defaultdict

    entry = frappe.get_doc("Stock Entry", stock_entry)
    entry.check_permission("write")
    if entry.docstatus != 1 or entry.purpose != "Material Issue" or entry.stock_entry_type != "Material Issue":
        frappe.throw(_("Only submitted Material Issues can have a historical Pick List repaired."))
    if entry.pick_list:
        frappe.throw(_("This Material Issue already has a Pick List reference."))
    pick = frappe.get_doc("Pick List", pick_list)
    pick.check_permission("read")
    if pick.docstatus != 1 or pick.purpose != "Material Issue" or pick.company != entry.company:
        frappe.throw(_("Select a submitted Material Issue Pick List belonging to the same company."))
    other = frappe.db.exists("Stock Entry", {
        "pick_list": pick.name, "name": ["!=", entry.name], "docstatus": ["!=", 2],
    })
    if other:
        frappe.throw(_("Pick List {0} is already linked to another Stock Entry.").format(pick.name))

    expected = defaultdict(float)
    actual = defaultdict(float)
    for row in entry.items:
        if flt(row.qty) > 0:
            expected[(row.item_code, row.s_warehouse)] += flt(
                row.transfer_qty or flt(row.qty) * flt(row.conversion_factor or 1))
            if row.get("custom_actual_storage_location"):
                frappe.throw(_("An issue row already has manual source attribution; review before restoring a Pick List."))
    for row in pick.locations:
        if not row.location or flt(row.picked_qty) <= 0:
            frappe.throw(_("Every Pick List row needs a physical location and picked quantity."))
        if frappe.db.get_value("Storage Location", row.location, "custom_warehouse") != row.warehouse:
            frappe.throw(_("Pick List has a source location outside its warehouse."))
        actual[(row.item_code, row.warehouse)] += flt(row.picked_qty)
    if set(actual) != set(expected) or any(abs(actual[key] - qty) > 1e-6 for key, qty in expected.items()):
        frappe.throw(_("The Pick List picked items and quantities must exactly match the submitted Material Issue."))

    frappe.db.set_value("Stock Entry", entry.name, "pick_list", pick.name, update_modified=False)
    entry.add_comment("Comment", _("Restored verified Pick List {0} as the location source for this submitted Material Issue. No Stock Ledger Entry changed.").format(pick.name))
    return {"stock_entry": entry.name, "pick_list": pick.name}
