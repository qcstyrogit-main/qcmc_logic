"""Conservative Material Transfer readiness for approved consolidated reorder rows."""
from decimal import Decimal

import frappe
from frappe.utils import cint
from qcmc_logic.dynamic_reorder_calculation import number
from qcmc_logic.utils import _can_serve_material_requests


def validate_transfer_source(company, source, destination, warehouses, read_only=True):
    """Require an explicit, same-company serving FG warehouse outside the target scope."""
    if not source:
        frappe.throw("Configure Transfer Source Warehouse on the Reorder Policy Mapping")
    if source == destination or source in warehouses:
        frappe.throw("Transfer source must be outside the replenishment warehouse scope")
    fields = ["company", "disabled", "is_group", "warehouse_type", "custom_is_province"]
    source_row = frappe.db.get_value("Warehouse", source, fields,
                                     as_dict=True, for_update=not read_only)
    target_row = frappe.db.get_value("Warehouse", destination, fields,
                                     as_dict=True, for_update=not read_only)
    for label, row in (("Source", source_row), ("Destination", target_row)):
        if (not row or row.company != company or cint(row.disabled) or cint(row.is_group)
                or row.warehouse_type != "Finished Goods"):
            frappe.throw(label + " must be an enabled leaf Finished Goods warehouse of the same company")
    if cint(source_row.custom_is_province) or not cint(target_row.custom_is_province):
        frappe.throw("Provincial replenishment requires a non-provincial source and provincial destination")
    if not _can_serve_material_requests(source):
        frappe.throw("Transfer Source Warehouse cannot serve Material Transfer requests")
    return source


def available_source_quantity(bin_row, commitments):
    """Do not treat future receipts as physical stock; conservatively deduct open commitments."""
    if not bin_row:
        return Decimal(0)
    physical = number(bin_row.get("actual_qty") or 0)
    reserved = sum((max(Decimal(0), number(bin_row.get(field) or 0)) for field in
        ("reserved_qty", "reserved_qty_for_production", "reserved_qty_for_sub_contract",
         "reserved_qty_for_production_plan")), Decimal(0))
    projected = number(bin_row.get("projected_qty") or 0)
    pending = sum((max(Decimal(0), number(row.get("stock_qty") or 0)) for row in commitments), Decimal(0))
    return max(Decimal(0), min(physical - reserved, projected) - pending)


def transfer_readiness(history, item_code, qty, read_only=True):
    """Validate the approved source and estimate current stock without reserving or moving it."""
    snapshot = frappe.parse_json(history.details or "{}")
    source = snapshot.get("transfer_source_warehouse")
    source = validate_transfer_source(history.company, source, history.warehouse,
                                      snapshot.get("warehouses") or [], read_only=read_only)
    lock = "" if read_only else " FOR UPDATE"
    bins = frappe.db.sql("""
        SELECT actual_qty, projected_qty, reserved_qty, reserved_qty_for_production,
               reserved_qty_for_sub_contract, reserved_qty_for_production_plan
        FROM `tabBin` WHERE item_code=%s AND warehouse=%s
    """ + lock, (item_code, source), as_dict=True)
    if len(bins) > 1:
        frappe.throw("Duplicate source Bin records require review")
    # Include drafts, and conservatively include the full quantity of open submitted requests.
    # This can understate availability but cannot turn a pending request into free stock.
    commitments = frappe.db.sql("""
        SELECT GREATEST(COALESCE(mri.stock_qty,0),
                        COALESCE(mri.qty,0)*COALESCE(NULLIF(mri.conversion_factor,0),1)) AS stock_qty
        FROM `tabMaterial Request Item` mri
        JOIN `tabMaterial Request` mr ON mr.name=mri.parent
        WHERE mr.company=%s AND mr.material_request_type='Material Transfer'
          AND mr.docstatus IN (0,1)
          AND COALESCE(mr.status,'Draft') NOT IN ('Stopped','Cancelled','Received','Issued','Transferred','Manufactured')
          AND mri.item_code=%s
          AND COALESCE(NULLIF(mri.from_warehouse,''), mr.set_from_warehouse)=%s
    """ + lock, (history.company, item_code, source), as_dict=True)
    available = available_source_quantity(bins[0] if bins else None, commitments)
    if available < number(qty):
        return "Insufficient Source Stock", "Available source quantity: " + str(available), source
    return "Ready", "", source
