"""Local-only real transfer draft, source checks and rollback.
Temporary warehouse, policy, mapping and approved history are test fixtures.
No stock ledger entry, existing MR changes, submission or commit.
Run in a fresh console with local users/workers not editing these records.
"""
from contextlib import ExitStack
from unittest.mock import patch
import frappe
from frappe.model.document import Document
from frappe.utils import cint
from qcmc_logic import dynamic_reorder_replenishment as engine
from qcmc_logic import dynamic_reorder_transfer as transfer
from qcmc_logic.dynamic_reorder_calculation import number
from qcmc_logic.dynamic_reorder_clock import business_date
from qcmc_logic import dynamic_reorder_audit as audit

ITEM = "EIB1048"
COMPANY = "Multiplast Corporation"
SOURCE = "FG - MC1"
PARENT = "Bacolod"


def run():
    if frappe.local.site != "erp.qcstyro.local" or frappe.session.user != "Administrator":
        frappe.throw("Fresh local Administrator console only")
    if cint(frappe.db.get_single_value("Stock Settings","auto_indent")) or engine.automatic_enabled():
        frappe.throw("Native and automatic replenishment must be disabled")
    def item_rows():
        return frappe.get_all("Item Reorder",filters={"parent":ITEM},fields=["*"],order_by="name")
    def bins():
        return frappe.get_all("Bin",filters={"item_code":ITEM},fields=["*"],order_by="name")
    def requests():
        return frappe.db.sql("""SELECT mr.name,mr.docstatus,mr.status,mr.modified,mri.name AS line_name,
            mri.stock_qty FROM `tabMaterial Request` mr JOIN `tabMaterial Request Item` mri
            ON mri.parent=mr.name WHERE mri.item_code=%s ORDER BY mr.name,mri.name""",(ITEM,),as_dict=True)
    def tree():
        return frappe.get_all("Warehouse",fields=["name","parent_warehouse","lft","rgt"],order_by="name")
    def settings():
        return frappe.get_single("Reorder Settings").as_dict()
    before_rows,before_bins,before_requests,before_tree,before_settings = item_rows(),bins(),requests(),tree(),settings()
    before_source = frappe.db.get_value("Warehouse",SOURCE,"custom_can_serve_material_requests")
    assert frappe.db.get_value("Warehouse",PARENT,"is_group") == 1
    names = []
    result_lines = []
    def forbid(*args,**kwargs):
        raise RuntimeError("Commit or submission forbidden during integration test")
    original_get_single = frappe.get_single
    def test_settings(doctype,*args,**kwargs):
        if doctype == "Reorder Settings":
            return frappe._dict(enabled=1,preview_only=0,automatic_update_enabled=0,
                                allow_new_reorder_rows=0,replenishment_mode="Manual Draft")
        return original_get_single(doctype,*args,**kwargs)
    try:
        with ExitStack() as stack:
            stack.enter_context(patch.object(frappe.db,"commit",side_effect=forbid))
            stack.enter_context(patch.object(Document,"submit",side_effect=forbid))
            stack.enter_context(patch.object(frappe,"enqueue",return_value=None))
            stack.enter_context(patch.object(frappe,"sendmail",return_value=None))
            stack.enter_context(patch.object(frappe,"publish_realtime",return_value=None))
            stack.enter_context(patch.object(frappe,"get_single",side_effect=test_settings))
            token = frappe.generate_hash(length=8)
            # If serving flags are configured, explicitly enable the source only in this transaction.
            if not transfer._can_serve_material_requests(SOURCE):
                frappe.db.set_value("Warehouse",SOURCE,"custom_can_serve_material_requests",1,update_modified=False)
                frappe.clear_document_cache("Warehouse",SOURCE)
            wh = frappe.get_doc(dict(doctype="Warehouse",warehouse_name="FG TEST Reorder "+token,
                company=COMPANY,parent_warehouse=PARENT,is_group=0,disabled=0,
                warehouse_type="Finished Goods",custom_is_province=1)).insert()
            names.append(("Warehouse",wh.name))
            policy = frappe.get_doc(dict(doctype="Reorder Policy",policy_name="Transfer TEST "+token,
                inventory_category="FG",inventory_type="INDUSTRIAL",enabled=1,
                material_request_type="Preserve",maximum_stock=0,automatic_update_enabled=0)).insert()
            names.append(("Reorder Policy",policy.name))
            mapping = frappe.get_doc(dict(doctype="Reorder Policy Mapping",mapping_name="Transfer TEST "+token,
                company=COMPANY,policy=policy.name,enabled=1,warehouses=[dict(warehouse=wh.name)],
                replenishment_warehouse=wh.name,transfer_source_warehouse=SOURCE,
                automatic_draft_replenishment=0)).insert()
            names.append(("Reorder Policy Mapping",mapping.name))
            assert transfer.validate_transfer_source(COMPANY,SOURCE,wh.name,[wh.name]) == SOURCE
            result_lines.append("PASS: real temporary provincial leaf, policy and mapping validated")
            item = frappe.get_doc("Item",ITEM,for_update=True)
            row = item.append("reorder_levels",dict(warehouse=wh.name,warehouse_group=wh.name,
                material_request_type="Transfer",warehouse_reorder_level=1000000,
                warehouse_reorder_qty=1000000,custom_managed_reorder=1,custom_reorder_mapping=mapping.name))
            item.save()
            names.append(("Item Reorder",row.name))
            # Synthetic approved calculation fixture; no claim of demand/approval integration here.
            snapshot = dict(schema_version=2,production_mode="Make to Stock",warehouses=[wh.name],
                transfer_source_warehouse=SOURCE,policy_snapshot=policy.as_dict(),
                applied_request_type="Transfer",company=COMPANY,mapping=mapping.name,
                warehouse=wh.name,item_code=ITEM,policy=policy.name,reorder_row=row.name,
                status="Approved",reorder_level=1000000,reorder_qty=1000000)
            history = audit.record(snapshot,frappe.generate_hash(length=24),business_date())
            names.append(("Reorder Calculation History",history))
            frappe.db.set_value("Item Reorder",row.name,"custom_reorder_history",history)
            result = engine.create_draft(history)
            assert result["status"] == "Insufficient Source Stock", result
            result_lines.append("PASS: real source stock shortage blocks draft creation")
            # Reduce only the temporary fixture to one stock unit, using real source Bin data.
            frappe.db.set_value("Item Reorder",row.name,dict(warehouse_reorder_level=1,warehouse_reorder_qty=1))
            snapshot.update(reorder_level=1,reorder_qty=1)
            frappe.db.set_value("Reorder Calculation History",history,
                dict(recommended_level=1,recommended_qty=1,details=frappe.as_json(snapshot)))
            frappe.clear_document_cache("Item",ITEM)
            frappe.clear_document_cache("Reorder Calculation History",history)
            result = engine.create_draft(history)
            assert result["status"] == "Draft Created", result
            names.append(("Material Request",result["name"]))
            mr = frappe.get_doc("Material Request",result["name"])
            assert mr.docstatus == 0 and mr.material_request_type == "Material Transfer"
            assert mr.company == COMPANY and mr.set_from_warehouse == SOURCE and mr.set_warehouse == wh.name
            assert mr.custom_replenishment_mapping == mapping.name and mr.custom_replenishment_history == history
            assert len(mr.items)==1
            line=mr.items[0]
            assert line.item_code==ITEM and line.from_warehouse==SOURCE and line.warehouse==wh.name
            assert number(line.stock_qty)==1
            result_lines.append("PASS: actual Material Transfer draft inserted: "+mr.name)
            result_lines.append("PASS: correct source, destination, quantity and audit links")
            duplicate = engine.create_draft(history)
            assert duplicate["status"]=="Open Material Request" and mr.name in duplicate["requests"], duplicate
            result_lines.append("PASS: second execution blocked by actual open draft")
            assert bins()==before_bins
            assert [r for r in requests() if r.name!=mr.name]==before_requests
            result_lines.append("PASS: physical/projected stock and existing requests unchanged")
    finally:
        frappe.db.rollback()
        frappe.clear_document_cache("Item",ITEM)
        frappe.clear_document_cache("Warehouse",SOURCE)
        for dt,name in names:
            frappe.clear_document_cache(dt,name)
    assert all(not frappe.db.exists(dt,name) for dt,name in names), names
    assert item_rows()==before_rows and bins()==before_bins and requests()==before_requests
    assert tree()==before_tree and settings()==before_settings
    assert frappe.db.get_value("Warehouse",SOURCE,"custom_can_serve_material_requests")==before_source
    result_lines.append("PASS: rollback removed all temporary records and restored original state")
    return result_lines
