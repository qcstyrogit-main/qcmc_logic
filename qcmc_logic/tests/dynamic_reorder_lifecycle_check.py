"""Opt-in local-only lifecycle check. Never commits or creates a real Material Request."""
from unittest.mock import patch
import frappe
from frappe.utils import nowdate
from qcmc_logic import dynamic_reorder_audit as audit
from qcmc_logic.dynamic_reorder_service import preview_rows
from qcmc_logic.dynamic_reorder_calculation import number
from erpnext.stock import reorder_item as standard_reorder

def run():
    if frappe.local.site != "erp.qcstyro.local" or frappe.session.user != "Administrator":
        frappe.throw("Run only as Administrator on erp.qcstyro.local")
    company, warehouse, item_code = "QC Styropackaging Corporation", "FG - Sta Clara", "EIEHB1BL50"
    settings = frappe.get_single(audit.SETTINGS)
    if not settings.preview_only or settings.automatic_update_enabled or settings.allow_new_reorder_rows:
        frappe.throw("Restore safe preview settings before running")
    before = frappe.get_all("Item Reorder", filters={"parent":item_code}, fields=["name","warehouse","warehouse_reorder_level","warehouse_reorder_qty","material_request_type"], order_by="name")
    if before:
        frappe.throw("Test expects the sample item's reorder table to be empty")
    existing = preview_rows(company,warehouse,item_code=item_code,as_of=nowdate(),period_method="Rolling Days",rolling_days=90)
    if len(existing)!=1 or existing[0]["status"]!="New Reorder Configuration":
        frappe.throw("Sample no longer eligible; review live data before testing")
    policy = existing[0]["policy"]
    if not frappe.db.exists("BOM",{"item":item_code,"docstatus":1,"is_active":1,"is_default":1}):
        frappe.throw("No eligible BOM")
    results = []
    history = None
    original_get_single = frappe.get_single
    def test_settings(doctype, *args, **kwargs):
        if doctype == audit.SETTINGS:
            return frappe._dict(enabled=1,preview_only=0,automatic_update_enabled=0,allow_new_reorder_rows=1)
        return original_get_single(doctype,*args,**kwargs)
    def forbid_commit(*args,**kwargs):
        raise RuntimeError("Commit forbidden during lifecycle test")
    def capture_requests(data):
        return data
    try:
        with patch.object(frappe.db,"commit",side_effect=forbid_commit), patch.object(frappe,"get_single",side_effect=test_settings):
            frappe.db.set_value("Reorder Policy",policy,{"material_request_type":"Manufacture","allow_new_reorder_rows":1,"automatic_update_enabled":0},update_modified=False)
            rows = preview_rows(company,warehouse,item_code=item_code,as_of=nowdate(),period_method="Rolling Days",rolling_days=90)
            assert len(rows)==1 and rows[0]["status"]=="New Reorder Configuration"
            row = rows[0]
            history = audit.record(row,frappe.generate_hash(length=24),nowdate())
            assert audit.apply_one(history) is True
            h = frappe.get_doc(audit.HISTORY,history)
            created = frappe.get_doc("Item Reorder",h.reorder_row)
            assert h.status=="Approved" and h.created_reorder_row
            assert created.warehouse==warehouse and created.material_request_type=="Manufacture"
            assert number(created.warehouse_reorder_level)==number(h.recommended_level)
            assert number(created.warehouse_reorder_qty)==number(h.recommended_qty)
            results.append("PASS: actual Item Reorder creation and approved values")
            candidates = standard_reorder.get_items_for_reorder()
            assert item_code in candidates
            only = {item_code:candidates[item_code]}
            with patch.object(standard_reorder,"get_items_for_reorder",return_value=only), patch.object(standard_reorder,"create_material_request",side_effect=capture_requests):
                high = standard_reorder._reorder_item()
                assert not high.get("Manufacture",{}).get(company,[])
                results.append("PASS: ERPNext does not request replenishment for current high stock")
                with patch.object(standard_reorder,"get_item_warehouse_projected_qty",return_value={item_code:{warehouse:0}}):
                    low = standard_reorder._reorder_item()
                    requests = low["Manufacture"][company]
                    assert len(requests)==1 and requests[0]["warehouse"]==warehouse
                    assert number(requests[0]["reorder_qty"])==max(number(h.recommended_level),number(h.recommended_qty))
                    results.append("PASS: standard ERPNext generates correct Manufacture request candidate at simulated zero stock (not submitted)")
            assert audit.rollback(history) is True
            assert frappe.get_doc(audit.HISTORY,history).status=="Reverted"
            assert not frappe.db.exists("Item Reorder",created.name)
            results.append("PASS: actual rollback removed the created reorder row")
    finally:
        frappe.db.rollback()
        frappe.clear_document_cache("Item",item_code)
        frappe.clear_document_cache("Reorder Policy",policy)
    after = frappe.get_all("Item Reorder",filters={"parent":item_code},fields=["name","warehouse","warehouse_reorder_level","warehouse_reorder_qty","material_request_type"],order_by="name")
    assert before==after
    assert not history or not frappe.db.exists(audit.HISTORY,history)
    results.append("PASS: original database state restored; no test history or reorder rows persisted")
    return results
