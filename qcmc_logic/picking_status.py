"""Operational picking status for Delivery Notes and picked Stock Entries.

A read-only display field; it never changes docstatus, workflow or stock.
"""
import frappe
from frappe import _
from frappe.utils import flt

FIELD = "custom_picking_status"
SUPPORTED_STOCK_TYPES = {"Material Issue", "Material Transfer for Manufacture"}


def _supported(doc):
    if doc.doctype == "Delivery Note":
        return not bool(doc.is_return)
    return (doc.doctype == "Stock Entry" and doc.stock_entry_type in SUPPORTED_STOCK_TYPES
            and doc.purpose == doc.stock_entry_type)


def _linked_names(doc):
    if doc.doctype == "Delivery Note":
        return {row.against_pick_list for row in doc.items if row.get("against_pick_list")}
    return {doc.pick_list} if doc.get("pick_list") else set()


def calculate(doc):
    if not _supported(doc):
        return ""
    if doc.docstatus == 2:
        return "Cancelled"
    if doc.docstatus == 1:
        return "Submitted"
    names = _linked_names(doc)
    if not names:
        from qcmc_logic.warehouse_transfer_allocation import warehouse_has_storage_locations
        rows = [row for row in doc.items if flt(row.qty) > 0]
        if doc.doctype == "Delivery Note":
            rows = [row for row in rows if frappe.get_cached_value("Item", row.item_code, "is_stock_item")]
        field = "warehouse" if doc.doctype == "Delivery Note" else "s_warehouse"
        if rows and all(row.get(field) for row in rows) and not any(
            warehouse_has_storage_locations(row.get(field)) for row in rows
        ):
            return "Not Required"
        return "Not Started"
    active = frappe.get_all("Pick List", filters={
        "name": ["in", sorted(names)], "docstatus": ["!=", 2],
    }, fields=["name", "docstatus"], limit_page_length=0)
    if len(active) != len(names):
        return "Pending Picking"
    if any(row.docstatus != 1 for row in active):
        return "Pending Picking"
    try:
        if doc.doctype == "Delivery Note":
            from qcmc_logic.delivery_note_pick_list import validate_delivery_pick_list_ready
            validate_delivery_pick_list_ready(doc)
        elif doc.stock_entry_type == "Material Issue":
            from qcmc_logic.stock_entry_material_issue_pick_list import validate_material_issue_picking
            validate_material_issue_picking(doc)
        else:
            from qcmc_logic.stock_entry_manufacture_pick_list import validate_manufacturing_transfer_pick_list
            validate_manufacturing_transfer_pick_list(doc)
    except (frappe.ValidationError, frappe.DoesNotExistError):
        frappe.clear_messages()
        return "Pending Picking"
    return "Picking Completed"


def sync_source(doc, method=None):
    if not frappe.get_meta(doc.doctype).has_field(FIELD):
        return
    value = calculate(doc)
    if doc.get(FIELD) != value:
        frappe.db.set_value(doc.doctype, doc.name, FIELD, value, update_modified=False)
        doc.set(FIELD, value)


def sync_pick_list(doc, method=None):
    """Update linked source records, including the custom Warehouse Transfer flow's exclusions."""
    parents = set(frappe.get_all("Delivery Note Item",
        filters={"against_pick_list": doc.name}, pluck="parent", limit_page_length=0))
    for name in parents:
        if frappe.db.exists("Delivery Note", name):
            sync_source(frappe.get_doc("Delivery Note", name))
    for name in frappe.get_all("Stock Entry", filters={"pick_list": doc.name},
                               pluck="name", limit_page_length=0):
        sync_source(frappe.get_doc("Stock Entry", name))


def sync_linked_reference(doctype, name):
    """Called when a source uses db.set_value to link a newly inserted Pick List."""
    if name and frappe.db.exists(doctype, name):
        sync_source(frappe.get_doc(doctype, name))


@frappe.whitelist()
def get_status(doctype, name):
    if doctype not in ("Delivery Note", "Stock Entry"):
        frappe.throw(_("Unsupported document type."), frappe.PermissionError)
    doc = frappe.get_doc(doctype, name)
    doc.check_permission("read")
    return {"status": calculate(doc), "pick_lists": sorted(_linked_names(doc))}


def ensure_fields():
    """Idempotent schema creation and one-time historical status reconciliation."""
    from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
    spec = {
        "fieldname": FIELD, "label": "Picking Status", "fieldtype": "Select",
        "options": "\nNot Required\nNot Started\nPending Picking\nPicking Completed\nSubmitted\nCancelled",
        "read_only": 1, "in_list_view": 1, "no_copy": 1,
        "allow_on_submit": 1, "insert_after": "docstatus",
        "description": "Read-only picking progress, independent of document workflow status.",
    }
    newly_created = {
        doctype: not frappe.db.exists("Custom Field", {"dt": doctype, "fieldname": FIELD})
        for doctype in ("Delivery Note", "Stock Entry")
    }
    create_custom_fields({
        "Delivery Note": [dict(spec, insert_after="customer")],
        "Stock Entry": [dict(spec, insert_after="stock_entry_type")],
    }, update=True)
    frappe.clear_cache(doctype="Delivery Note")
    frappe.clear_cache(doctype="Stock Entry")
    for doctype in ("Delivery Note", "Stock Entry"):
        # Reconcile historical documents only on the initial field installation,
        # not on every subsequent site migration.
        if not newly_created[doctype]:
            continue
        for name in frappe.get_all(doctype, pluck="name", limit_page_length=0):
            sync_source(frappe.get_doc(doctype, name))
