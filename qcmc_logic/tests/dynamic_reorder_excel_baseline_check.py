"""Local-only rollback integration for exact Excel baseline approval."""
from contextlib import ExitStack
from unittest.mock import patch
import frappe
from frappe.model.document import Document
from qcmc_logic import dynamic_reorder_adoption as adoption
from qcmc_logic import dynamic_reorder_excel_baseline as baseline
from qcmc_logic import dynamic_reorder_replenishment as replenishment

ITEM = "EIB1048"
COMPANY = "QC Styropackaging Corporation"
STA = "FG - Sta Clara"
GUYONG = "FG - Guyong"


def run():
    assert frappe.local.site == "erp.qcstyro.local"
    assert frappe.session.user == "Administrator"
    assert not frappe.db.get_single_value("Stock Settings", "auto_indent")
    def rows():
        return frappe.get_all("Item Reorder", fields=["*"], order_by="name")
    def values(row):
        return tuple(row.get(f) for f in ("parent","warehouse","warehouse_group",
            "warehouse_reorder_level","warehouse_reorder_qty","material_request_type"))
    before = rows()
    before_history = frappe.db.count("Reorder Calculation History")
    before_requests = frappe.db.count("Material Request")
    names = []
    checks = []
    real_get_single = frappe.get_single
    def get_single(doctype,*args,**kwargs):
        if doctype == "Reorder Settings":
            return frappe._dict(enabled=0,preview_only=1,automatic_update_enabled=0,
                                allow_new_reorder_rows=0,replenishment_mode="Disabled")
        return real_get_single(doctype,*args,**kwargs)
    def forbid(*args,**kwargs):
        raise RuntimeError("Commit or submit prohibited")
    try:
        with ExitStack() as stack:
            for target,attr in ((frappe.db,"commit"),(Document,"submit")):
                stack.enter_context(patch.object(target,attr,side_effect=forbid))
            for attr in ("enqueue","sendmail","publish_realtime"):
                stack.enter_context(patch.object(frappe,attr,return_value=None))
            stack.enter_context(patch.object(frappe,"get_single",side_effect=get_single))
            assert not frappe.db.exists("Item Reorder",{"parent":ITEM,"warehouse":["in",[STA,GUYONG]]})
            token = frappe.generate_hash(length=8)
            policy = frappe.get_doc(dict(doctype="Reorder Policy",policy_name="Excel TEST "+token,
                inventory_category="FG",inventory_type="INDUSTRIAL",enabled=1,
                material_request_type="Manufacture",automatic_update_enabled=0)).insert()
            names.append(("Reorder Policy",policy.name))
            mapping = frappe.get_doc(dict(doctype="Reorder Policy Mapping",mapping_name="Excel TEST "+token,
                company=COMPANY,policy=policy.name,enabled=1,
                warehouses=[dict(warehouse=STA),dict(warehouse=GUYONG)],
                replenishment_warehouse=STA,automatic_draft_replenishment=0)).insert()
            names.append(("Reorder Policy Mapping",mapping.name))
            item = frappe.get_doc("Item",ITEM,for_update=True)
            for wh in (STA,GUYONG):
                item.append("reorder_levels",dict(warehouse=wh,warehouse_group=wh,
                    material_request_type="Manufacture",warehouse_reorder_level=123.456789,
                    warehouse_reorder_qty=456))
            item.save()
            sta,guyong = [r for r in item.reorder_levels if r.warehouse in (STA,GUYONG)]
            ids = {sta.name,guyong.name}
            names.extend(("Item Reorder",n) for n in ids)
            def scoped_inventory():
                return adoption.inventory_plan([r for r in adoption._read_inventory_rows() if r.name in ids],
                    {STA:(1,"Manufacture")},{GUYONG:(1,"Manufacture")})
            stack.enter_context(patch.object(adoption,"inspect_import",side_effect=scoped_inventory))
            # Use reviewed test fixture instead of the 881-row production workbook.
            terms = dict(sheet="QC",level="123.456789",qty="456",lead_days="7",
                safety_days="14",minimum="456",maximum="912")
            stack.enter_context(patch.object(baseline.Path,"read_bytes",return_value=b"fixture"))
            stack.enter_context(patch.object(baseline,"read_workbook",return_value={(ITEM,STA):terms}))
            original = rows()
            plan = baseline.approve()
            assert plan["count"] == 1 and plan["ready"]
            assert rows() == original
            assert frappe.db.count("Reorder Calculation History") == before_history
            checks.append("PASS: baseline preview read-only")
            try:
                baseline.approve("stale",apply=True)
            except frappe.ValidationError:
                frappe.clear_messages()
            else:
                raise AssertionError("Accepted stale digest")
            assert rows() == original
            checks.append("PASS: stale approval digest rejected")
            real_set = frappe.db.set_value
            def fail_history(dt,name,*args,**kwargs):
                if dt=="Item Reorder" and args and args[0]=="custom_reorder_history":
                    raise RuntimeError("Injected failure")
                return real_set(dt,name,*args,**kwargs)
            with patch.object(frappe.db,"set_value",side_effect=fail_history):
                try:
                    baseline.approve(plan["digest"],apply=True)
                except RuntimeError as exc:
                    assert str(exc)=="Injected failure"
                else:
                    raise AssertionError("Expected rollback")
            assert rows()==original
            assert frappe.db.count("Reorder Calculation History")==before_history
            checks.append("PASS: failure rolls back adoption and history together")
            result = baseline.approve(plan["digest"],apply=True)
            assert result["count"]==1 and result["excluded"]==1
            updated = {r.name:r for r in rows()}
            assert {r.name:values(r) for r in original}=={n:values(r) for n,r in updated.items()}
            s,g = updated[sta.name],updated[guyong.name]
            assert s.custom_managed_reorder and s.custom_reorder_history
            assert g.custom_reorder_excluded_mapping==mapping.name and not g.custom_reorder_history
            h=frappe.get_doc("Reorder Calculation History",s.custom_reorder_history)
            names.append(("Reorder Calculation History",h.name))
            snap=frappe.parse_json(h.details)
            assert h.status=="Approved" and h.applied_by=="Administrator"
            assert snap["approval_source"]=="Excel Baseline" and snap["excel_terms"]==terms
            checks.append("PASS: real history approved without changing any reorder values")
            # Read-only replenishment uses the exact approved quantities and QC limits.
            state=replenishment.approved_state(h.name,read_only=True)
            assert state[2].excel_baseline and str(state[2].lead_time)=="7"
            assert str(state[2].maximum_stock)=="912"
            checks.append("PASS: approved baseline usable by replenishment assessment")
            try:
                replenishment.approved_state(h.name,automatic=True,read_only=True)
            except frappe.ValidationError:
                frappe.clear_messages()
            else:
                raise AssertionError("Automatic baseline permitted")
            checks.append("PASS: automatic baseline draft rejected")
            try:
                baseline.approve()
            except ValueError:
                pass
            else:
                raise AssertionError("Repeat baseline approval allowed")
            checks.append("PASS: repeat approval rejected")
            assert frappe.db.count("Material Request")==before_requests
    finally:
        frappe.db.rollback()
        frappe.clear_document_cache("Item",ITEM)
        for dt,name in names:
            frappe.clear_document_cache(dt,name)
    assert rows()==before
    assert frappe.db.count("Reorder Calculation History")==before_history
    assert frappe.db.count("Material Request")==before_requests
    assert all(not frappe.db.exists(dt,name) for dt,name in names)
    checks.append("PASS: complete rollback; no persistent rows or Material Requests")
    return checks
