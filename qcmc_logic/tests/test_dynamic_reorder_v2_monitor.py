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
        from qcmc_logic import dynamic_reorder_monitor as m
        with patch.object(m,"preview_rows",return_value=[self.row()]),patch.object(frappe,"db",MagicMock()) as db:
            db.sql.return_value=[frappe._dict(name="MR",item_code="I")]
            rows=m.monitor_rows("Co","M")
            self.assertEqual(rows[0]["monitor_status"],"Open Material Request")
            sql,params=db.sql.call_args.args
            self.assertIn("docstatus IN (0,1)",sql)
            self.assertIn(("A","B"),params)
            db.set_value.assert_not_called(); db.commit.assert_not_called()
