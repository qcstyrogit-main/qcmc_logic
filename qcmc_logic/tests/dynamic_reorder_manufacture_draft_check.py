"""Local-only real draft insertion with simulated shortage and no commits.

This checks document insertion, not eligibility: the existing open request is
omitted only from the in-process test fixture. No existing request is modified.
Run in a fresh local Administrator console with no pending changes.
"""
from contextlib import ExitStack
from unittest.mock import patch
from decimal import Decimal
import frappe
from frappe.model.document import Document
from frappe.utils import cint
from qcmc_logic import dynamic_reorder_replenishment as engine
from qcmc_logic.dynamic_reorder_calculation import number

HISTORY = "2vff1taqrv"
EXISTING = "MC-MC1-FGWRF-2611-00001"
ITEM = "EIB1048"


def run():
    if frappe.local.site != "erp.qcstyro.local" or frappe.session.user != "Administrator":
        frappe.throw("Fresh local Administrator console only")
    if cint(frappe.db.get_single_value("Stock Settings", "auto_indent")) or engine.automatic_enabled():
        frappe.throw("Native and automatic replenishment must be disabled")
    def bin_snapshot():
        return frappe.get_all("Bin", filters={"item_code": ITEM,
            "warehouse": ["in", ["FG - MC1", "FG - MC2"]]},
            fields=["name","warehouse","actual_qty","projected_qty","indented_qty",
                    "planned_qty","ordered_qty","reserved_qty"], order_by="name")
    def request_snapshot():
        return frappe.db.get_value("Material Request", EXISTING,
            ["name","docstatus","status","modified"], as_dict=True)
    original_bins = bin_snapshot()
    original_request = request_snapshot()
    original_history = frappe.db.get_value("Reorder Calculation History", HISTORY,
        ["status","recommended_level","recommended_qty","modified"], as_dict=True)
    draft_name = None
    results = []
    def forbid(*args, **kwargs):
        raise RuntimeError("Commit or submission forbidden during integration test")
    try:
        state = engine.approved_state(HISTORY, read_only=True)
        h, item, policy, request_type, projected, qty, requests = state
        assert item.name == ITEM and request_type == "Manufacture"
        assert EXISTING in requests and original_request.docstatus == 1
        assert engine.manufacturing_readiness(ITEM,h.company,request_type)[0] == "Ready"
        precision = 0 if frappe.db.get_value("UOM",item.stock_uom,"must_be_whole_number") else cint(frappe.db.get_default("float_precision") or 3)
        simulated_projected = Decimal(0)
        simulated_qty = engine.candidate_quantity(h.recommended_level,h.recommended_qty,simulated_projected,precision)
        assert simulated_qty > 0
        if number(policy.maximum_stock or 0) and simulated_qty > number(policy.maximum_stock):
            frappe.throw("Simulated shortage exceeds policy maximum; review test fixture")
        # No Bin or existing MR writes. Substitute eligibility result only in this call.
        fixture = (h,item,policy,request_type,simulated_projected,simulated_qty,[])
        with ExitStack() as stack:
            stack.enter_context(patch.object(frappe.db,"commit",side_effect=forbid))
            stack.enter_context(patch.object(Document,"submit",side_effect=forbid))
            stack.enter_context(patch.object(frappe,"enqueue",return_value=None))
            stack.enter_context(patch.object(frappe,"sendmail",return_value=None))
            stack.enter_context(patch.object(frappe,"publish_realtime",return_value=None))
            with patch.object(engine,"approved_state",return_value=fixture):
                result = engine.create_draft(HISTORY)
            assert result["status"] == "Draft Created", result
            draft_name = result["name"]
            mr = frappe.get_doc("Material Request",draft_name)
            assert mr.docstatus == 0 and mr.material_request_type == "Manufacture"
            assert mr.company == h.company and len(mr.items) == 1
            assert mr.custom_replenishment_mapping == h.mapping
            assert mr.custom_replenishment_history == HISTORY
            line = mr.items[0]
            assert line.item_code == ITEM and line.warehouse == h.warehouse
            assert number(line.stock_qty) == simulated_qty, (line.stock_qty,simulated_qty)
            assert bin_snapshot() == original_bins
            assert request_snapshot() == original_request
            results.append("PASS: actual Manufacture draft inserted: " + draft_name)
            results.append("PASS: correct item, destination, history and quantity " + str(simulated_qty))
            results.append("PASS: draft not submitted; stock and existing request unchanged")
            # Restore the real eligibility path. The new uncommitted draft must be visible.
            current = engine.approved_state(HISTORY,read_only=True)
            assert draft_name in current[-1] and EXISTING in current[-1], current[-1]
            results.append("PASS: real open-request lookup detects the new draft")
    finally:
        frappe.db.rollback()
        frappe.clear_document_cache("Reorder Calculation History",HISTORY)
    assert draft_name and not frappe.db.exists("Material Request",draft_name)
    assert bin_snapshot() == original_bins
    assert request_snapshot() == original_request
    assert frappe.db.get_value("Reorder Calculation History",HISTORY,
        ["status","recommended_level","recommended_qty","modified"],as_dict=True) == original_history
    results.append("PASS: rollback removed test draft; original request, history and stock preserved")
    return results
