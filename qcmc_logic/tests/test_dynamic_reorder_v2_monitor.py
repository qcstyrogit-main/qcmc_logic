import unittest
from unittest.mock import patch, MagicMock
import frappe


class TestReplenishmentMonitor(unittest.TestCase):
    def row(self, **kwargs):
        return dict(item_code="I",company="Co",mapping="M",warehouses=["A","B"],warehouse="A",status="Preview",
                    production_mode="Make to Stock",projected_qty=30,reorder_level=40,reorder_qty=20) | kwargs

    def test_threshold_uses_combined_projected_and_equal_boundary(self):
        from qcmc_logic.dynamic_reorder_monitor import assess
        self.assertEqual(assess(self.row(projected_qty=50),[])["monitor_status"],"Above Reorder Level")
        r=assess(self.row(projected_qty=40),[])
        self.assertEqual(r["candidate_qty"],20)
        self.assertFalse(r["can_create_request"])
        self.assertEqual(r["monitor_status"],"Preview Candidate")
        self.assertEqual(assess(self.row(projected_qty=-10),[])["candidate_qty"],50)

    def test_no_requests_for_mto_unreliable_or_legacy_conflicts(self):
        from qcmc_logic.dynamic_reorder_monitor import assess
        for row,status in ((self.row(production_mode="Make to Order"),"Make to Order"),
                           (self.row(status="Failed"),"Review Required"),
                           (self.row(legacy_reorder_rows=["old"]),"Legacy Reorder Conflict")):
            r=assess(row,[])
            self.assertEqual(r["monitor_status"],status)
            self.assertEqual(r["candidate_qty"],0)
            self.assertFalse(r["can_create_request"])

    def test_open_requests_suppress_instead_of_subtracting_from_projected_again(self):
        from qcmc_logic.dynamic_reorder_monitor import assess
        r=assess(self.row(),[dict(name="MR-1"),dict(name="MR-2")])
        self.assertEqual(r["candidate_qty"],0)
        self.assertEqual(r["monitor_status"],"Open Material Request")
        self.assertEqual(r["open_material_requests"],["MR-1","MR-2"])

    def test_report_queries_open_draft_and_submitted_requests_for_all_warehouses(self):
        from datetime import date
        import json
        from qcmc_logic import dynamic_reorder_monitor as m
        from qcmc_logic import dynamic_reorder_replenishment as r
        from qcmc_logic import dynamic_reorder_service as service
        from qcmc_logic import dynamic_reorder_clock as clock
        today=date(2026,11,27)
        config=frappe._dict(enabled=1,warehouses=[frappe._dict(warehouse=w) for w in ("A","B")],
            replenishment_warehouse="A")
        policy=frappe._dict(name="P",enabled=1,inventory_category="FG",inventory_type="INDUSTRIAL",
            material_request_type="Manufacture",maximum_stock=0)
        row=frappe._dict(name="R",parent="I",warehouse="A",warehouse_group="A",
            custom_managed_reorder=1,custom_reorder_mapping="M",custom_reorder_history="H",
            warehouse_reorder_level=40,warehouse_reorder_qty=20,material_request_type="Manufacture")
        item=frappe._dict(name="I",item_name="Item",stock_uom="PCS",disabled=0,is_stock_item=1,
            has_variants=0,end_of_life=None,custom_inventory_group="FG",
            custom_inventory_type_="INDUSTRIAL",reorder_levels=[row])
        history=frappe._dict(name="H",status="Approved",company="Co",mapping="M",policy="P",
            warehouse="A",item_code="I",reorder_row="R",recommended_level=40,recommended_qty=20,
            details=json.dumps(dict(schema_version=2,production_mode="Make to Stock",warehouses=["A","B"],
                policy_snapshot=dict(policy),applied_request_type="Manufacture")))
        records={"Item":[item],"Item Reorder":[row],"Bin":[frappe._dict(item_code="I",projected_qty=30)],
            "Warehouse":[frappe._dict(name=w,parent_warehouse=None) for w in ("A","B")]}
        docs={"Item":item,"Reorder Policy":policy,"Reorder Calculation History":history}
        with patch.object(frappe,"session",frappe._dict(user="Administrator")), \
             patch.object(frappe,"db",MagicMock()) as db, \
             patch.object(frappe,"get_all",side_effect=lambda dt,**kw: records[dt]), \
             patch.object(frappe,"get_doc",side_effect=lambda dt,*a,**kw: docs[dt]), \
             patch.object(frappe,"get_single",return_value=frappe._dict(enabled=0,preview_only=1)), \
             patch.object(service,"load_mapping",return_value=(config,policy)), \
             patch.object(r,"load_mapping",return_value=(config,policy)), \
             patch.object(clock,"business_date",return_value=today), \
             patch.object(r,"business_date",return_value=today), \
             patch.object(r,"manual_enabled",return_value=False), \
             patch.object(r,"manufacturing_readiness",return_value=("Ready","","BOM-I")):
            db.exists.return_value=False
            db.get_value.return_value=1
            db.sql.side_effect=[[frappe._dict(projected_qty=30)],[frappe._dict(name="MR")]]
            rows=m.monitor_rows("Co","M")
            self.assertEqual(rows[0]["monitor_status"],"Open Material Request")
            self.assertEqual(rows[0]["open_material_requests"],["MR"])
            sql,params=db.sql.call_args.args
            self.assertIn("docstatus IN (0,1)",sql)
            self.assertIn(("A","B"),params)
            self.assertNotIn("FOR UPDATE",sql)
            db.set_value.assert_not_called(); db.commit.assert_not_called()
