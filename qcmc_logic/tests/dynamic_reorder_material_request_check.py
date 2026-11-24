"""Local-only, transaction-rolled-back standard Manufacture Material Request integration test."""
from contextlib import ExitStack
from unittest.mock import patch
from math import ceil
import frappe
from frappe.utils import nowdate, flt
from qcmc_logic import dynamic_reorder_audit as audit
from qcmc_logic.dynamic_reorder_service import preview_rows
from erpnext.stock import reorder_item as standard

def run():
    if frappe.local.site != "erp.qcstyro.local" or frappe.session.user != "Administrator":
        frappe.throw("Local Administrator only")
    company, warehouse, item = "QC Styropackaging Corporation", "FG - Sta Clara", "EIEHB1BL50"
    settings=frappe.get_single(audit.SETTINGS)
    if not settings.enabled or not settings.preview_only or settings.automatic_update_enabled or settings.allow_new_reorder_rows:
        frappe.throw("Restore safe preview settings before running")
    if frappe.db.exists("Item Reorder",{"parent":item}):
        frappe.throw("Expected an empty sample reorder table")
    rows=preview_rows(company,warehouse,item_code=item,as_of=nowdate(),period_method="Rolling Days",rolling_days=90)
    if len(rows)!=1 or rows[0]["status"]!="New Reorder Configuration":
        frappe.throw("Sample no longer eligible")
    policy=rows[0]["policy"]
    def bin_state():
        return frappe.db.get_value("Bin",{"item_code":item,"warehouse":warehouse},
            ["actual_qty","projected_qty","indented_qty","ordered_qty","planned_qty","reserved_qty"],as_dict=True)
    before=bin_state()
    policy_before=frappe.db.get_value("Reorder Policy",policy,["material_request_type","allow_new_reorder_rows","automatic_update_enabled"],as_dict=True)
    original_get_single=frappe.get_single
    def test_settings(doctype,*args,**kwargs):
        if doctype==audit.SETTINGS:
            return frappe._dict(enabled=1,preview_only=0,automatic_update_enabled=0,allow_new_reorder_rows=1)
        return original_get_single(doctype,*args,**kwargs)
    def forbid_commit(*args,**kwargs):
        raise RuntimeError("Commit forbidden in this test")
    def fail_errors(errors):
        raise RuntimeError("ERPNext Material Request generation failed: "+ "; ".join(str(e) for e in errors))
    results=[]
    history=mr_name=None
    try:
        with ExitStack() as stack:
            stack.enter_context(patch.object(frappe.db,"commit",side_effect=forbid_commit))
            stack.enter_context(patch.object(frappe,"get_single",side_effect=test_settings))
            stack.enter_context(patch.object(frappe,"sendmail",return_value=None))
            stack.enter_context(patch.object(frappe,"enqueue",return_value=None))
            stack.enter_context(patch.object(frappe,"publish_realtime",return_value=None))
            stack.enter_context(patch.object(standard,"send_email_notification",return_value=None))
            stack.enter_context(patch.object(standard,"notify_errors",side_effect=fail_errors))
            frappe.db.set_value("Reorder Policy",policy,{"material_request_type":"Manufacture","allow_new_reorder_rows":1,"automatic_update_enabled":0},update_modified=False)
            rows=preview_rows(company,warehouse,item_code=item,as_of=nowdate(),period_method="Rolling Days",rolling_days=90)
            assert len(rows)==1 and rows[0]["status"]=="New Reorder Configuration"
            history=audit.record(rows[0],frappe.generate_hash(length=24),nowdate())
            assert audit.apply_one(history) is True
            h=frappe.get_doc(audit.HISTORY,history)
            candidates=standard.get_items_for_reorder()
            assert item in candidates and len(candidates[item])==1
            only={item:candidates[item]}
            assert only[item][0].material_request_type=="Manufacture"
            results.append("PASS: approved reorder configuration is visible to the standard engine")
            with patch.object(standard,"get_items_for_reorder",return_value=only):
                high=standard._reorder_item()
                assert not high, high
                results.append("PASS: actual high stock produces no Material Request")
                with patch.object(standard,"get_item_warehouse_projected_qty",return_value={item:{warehouse:0}}):
                    generated=standard._reorder_item()
            assert len(generated)==1, generated
            mr_name=generated[0].name
            mr=frappe.get_doc("Material Request",mr_name)
            assert mr.docstatus==1 and mr.auto_created_via_reorder and mr.material_request_type=="Manufacture"
            assert mr.company==company and len(mr.items)==1
            line=mr.items[0]
            expected=max(h.recommended_level,h.recommended_qty)
            if frappe.db.get_value("UOM",line.uom,"must_be_whole_number"):
                expected=ceil(expected)
            assert line.item_code==item and line.warehouse==warehouse
            assert flt(line.stock_qty,line.precision("stock_qty"))==flt(expected,line.precision("stock_qty"))
            results.append("PASS: actual submitted Manufacture Material Request; correct item, company, warehouse and quantity "+str(line.stock_qty))
            submitted=bin_state()
            assert submitted.actual_qty==before.actual_qty
            results.append("PASS: request submission leaves physical stock unchanged")
            mr.cancel()
            assert frappe.db.get_value("Material Request",mr_name,"docstatus")==2
            results.append("PASS: Material Request cancellation")
            assert audit.rollback(history) is True
            assert not frappe.db.exists("Item Reorder",h.reorder_row)
            results.append("PASS: reorder configuration rollback")
    finally:
        frappe.db.rollback()
        frappe.clear_document_cache("Item",item)
        frappe.clear_document_cache("Reorder Policy",policy)
    assert not frappe.db.exists("Item Reorder",{"parent":item})
    assert not history or not frappe.db.exists(audit.HISTORY,history)
    assert not mr_name or not frappe.db.exists("Material Request",mr_name)
    assert bin_state()==before
    assert frappe.db.get_value("Reorder Policy",policy,["material_request_type","allow_new_reorder_rows","automatic_update_enabled"],as_dict=True)==policy_before
    results.append("PASS: original Bin and policy restored; no test requests, history or reorder rows persisted")
    return results
