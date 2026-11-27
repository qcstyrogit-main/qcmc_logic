"""Local-only adoption and Guyong protection integration; always rolls back.

Use actual DB rows, mappings, locks and adoption writes. Restrict only the
inventory manifest to two temporary rows because the local dataset differs
from the reviewed production import. Never run on production.
"""
from contextlib import ExitStack
from unittest.mock import patch
import frappe
from frappe.model.document import Document
from frappe.utils import cint
from qcmc_logic import dynamic_reorder_adoption as adoption
from qcmc_logic import dynamic_reorder_native_guard as guard
from qcmc_logic.dynamic_reorder_policy import reviewed_preserved_row
from qcmc_logic import dynamic_reorder_service as service

ITEM = "EIB1048"
COMPANY = "QC Styropackaging Corporation"
STA = "FG - Sta Clara"
GUYONG = "FG - Guyong"


def run():
    if frappe.local.site != "erp.qcstyro.local" or frappe.session.user != "Administrator":
        frappe.throw("Fresh local Administrator console only")
    settings = frappe.get_single("Reorder Settings")
    if cint(frappe.db.get_single_value("Stock Settings","auto_indent")) or settings.get("replenishment_mode") == "Automatic Draft":
        frappe.throw("Native and automatic replenishment must be disabled")
    def all_reorder():
        return frappe.get_all("Item Reorder",fields=["*"],order_by="name")
    def values(row):
        return tuple(row.get(f) for f in ("parent","warehouse","warehouse_group",
            "warehouse_reorder_level","warehouse_reorder_qty","material_request_type"))
    before = all_reorder()
    original_settings = settings.as_dict()
    before_requests = frappe.db.count("Material Request")
    before_history = frappe.db.count("Reorder Calculation History")
    names = []
    lines = []
    def forbid(*args, **kwargs):
        raise RuntimeError("Commit or submission forbidden")
    original_get_single = frappe.get_single
    def disabled_settings(doctype,*args,**kwargs):
        if doctype=="Reorder Settings":
            return frappe._dict(enabled=0,preview_only=1,automatic_update_enabled=0,
                                allow_new_reorder_rows=0,replenishment_mode="Disabled")
        return original_get_single(doctype,*args,**kwargs)
    try:
        with ExitStack() as stack:
            stack.enter_context(patch.object(frappe.db,"commit",side_effect=forbid))
            stack.enter_context(patch.object(Document,"submit",side_effect=forbid))
            stack.enter_context(patch.object(frappe,"enqueue",return_value=None))
            stack.enter_context(patch.object(frappe,"sendmail",return_value=None))
            stack.enter_context(patch.object(frappe,"publish_realtime",return_value=None))
            stack.enter_context(patch.object(frappe,"get_single",side_effect=disabled_settings))
            token=frappe.generate_hash(length=8)
            assert not frappe.db.exists("Item Reorder",{"parent":ITEM,"warehouse":["in",[STA,GUYONG]]}), "Sample already has Sta Clara/Guyong rows"
            policy=frappe.get_doc(dict(doctype="Reorder Policy",policy_name="Adoption TEST "+token,
                inventory_category="FG",inventory_type="INDUSTRIAL",enabled=1,
                material_request_type="Manufacture",automatic_update_enabled=0)).insert()
            names.append(("Reorder Policy",policy.name))
            mapping=frappe.get_doc(dict(doctype="Reorder Policy Mapping",mapping_name="Adoption TEST "+token,
                company=COMPANY,policy=policy.name,enabled=1,warehouses=[dict(warehouse=STA),dict(warehouse=GUYONG)],
                replenishment_warehouse=STA,automatic_draft_replenishment=0)).insert()
            names.append(("Reorder Policy Mapping",mapping.name))
            item=frappe.get_doc("Item",ITEM,for_update=True)
            sta=item.append("reorder_levels",dict(warehouse=STA,warehouse_group=STA,
                material_request_type="Manufacture",warehouse_reorder_level=123,warehouse_reorder_qty=456))
            guyong=item.append("reorder_levels",dict(warehouse=GUYONG,warehouse_group=GUYONG,
                material_request_type="Manufacture",warehouse_reorder_level=321,warehouse_reorder_qty=654))
            item.save()
            names.extend([("Item Reorder",sta.name),("Item Reorder",guyong.name)])
            ids={sta.name,guyong.name}
            def scoped_inventory():
                # Real SQL and classifier; only the expected manifest differs locally.
                rows=[r for r in adoption._read_inventory_rows() if r.name in ids]
                return adoption.inventory_plan(rows,{STA:(1,"Manufacture")},{GUYONG:(1,"Manufacture")})
            stack.enter_context(patch.object(adoption,"inspect_import",side_effect=scoped_inventory))
            baseline=all_reorder()
            original={r.name:values(r) for r in baseline}
            plan=adoption.adopt_existing()
            assert plan["ready"] and plan["count"]==1 and plan["exclusion_count"]==1, plan
            assert all_reorder()==baseline
            lines.append("PASS: real adoption dry-run identifies exact rows without writes")
            try:
                adoption.adopt_existing(expected_digest="stale",apply=True)
            except frappe.ValidationError:
                frappe.clear_messages()
            else:
                raise AssertionError("Stale digest accepted")
            assert all_reorder()==baseline
            lines.append("PASS: stale review digest blocked without writes")
            # Force a failure at the second write; verify the first write is undone by savepoint.
            original_set_value=frappe.db.set_value
            def fail_second(dt,name,*args,**kwargs):
                if dt=="Item Reorder" and name==guyong.name:
                    raise RuntimeError("Injected exclusion failure")
                return original_set_value(dt,name,*args,**kwargs)
            with patch.object(frappe.db,"set_value",side_effect=fail_second):
                try:
                    adoption.adopt_existing(expected_digest=plan["digest"],apply=True)
                except RuntimeError as exc:
                    assert str(exc)=="Injected exclusion failure"
                else:
                    raise AssertionError("Expected adoption failure")
            assert all_reorder()==baseline
            lines.append("PASS: partial adoption failure rolls back all ownership writes")
            result=adoption.adopt_existing(expected_digest=plan["digest"],apply=True)
            assert result["count"]==1 and result["excluded"]==1, result
            after=all_reorder()
            assert {r.name:values(r) for r in after}==original
            assert [r for r in after if r.name not in ids]==[r for r in baseline if r.name not in ids]
            by_name={r.name:r for r in after}
            s,g=by_name[sta.name],by_name[guyong.name]
            assert s.custom_managed_reorder==1 and s.custom_reorder_mapping==mapping.name
            assert not s.custom_reorder_history
            assert not g.custom_managed_reorder and not g.custom_reorder_mapping and not g.custom_reorder_history
            assert g.custom_reorder_excluded_mapping==mapping.name
            lines.append("PASS: actual adoption updates ownership only; ROL, ROQ and request types preserved")
            assert reviewed_preserved_row(g,s,mapping.name,[STA,GUYONG])
            assert not reviewed_preserved_row(g,s,"Other",[STA,GUYONG])
            assert not reviewed_preserved_row(dict(g,custom_reorder_excluded_mapping=None),s,mapping.name,[STA,GUYONG])
            preview=service.preview_rows(COMPANY,mapping=mapping.name,item_code=ITEM)
            assert len(preview)==1 and preview[0].get("reorder_row")==sta.name, preview
            assert preview[0].get("legacy_reorder_rows")==[], preview
            lines.append("PASS: real consolidated preview uses Sta Clara and excludes reviewed Guyong row")
            native=frappe._dict(auto_created_via_reorder=1,items=[frappe._dict(item_code=ITEM,warehouse=w) for w in (STA,GUYONG)])
            protected=guard.protected_pairs(native)
            assert (ITEM,STA) in protected and (ITEM,GUYONG) in protected, protected
            native.auto_created_via_reorder=0
            assert guard.protected_pairs(native)==set()
            lines.append("PASS: native guard protects both rows; manual requests unaffected")
            repeat=adoption.adopt_existing()
            assert not repeat["ready"] and not repeat["count"], repeat
            lines.append("PASS: already adopted configuration cannot be adopted again")
            assert frappe.db.count("Material Request")==before_requests
            assert frappe.db.count("Reorder Calculation History")==before_history
    finally:
        frappe.db.rollback()
        frappe.clear_document_cache("Item",ITEM)
        for dt,name in names:
            frappe.clear_document_cache(dt,name)
    assert all(not frappe.db.exists(dt,name) for dt,name in names), names
    assert all_reorder()==before
    assert frappe.get_single("Reorder Settings").as_dict()==original_settings
    assert frappe.db.count("Material Request")==before_requests
    assert frappe.db.count("Reorder Calculation History")==before_history
    lines.append("PASS: complete rollback; original configuration, settings and requests unchanged")
    return lines
