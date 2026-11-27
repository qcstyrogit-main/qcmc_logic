"""Read-only monitor result tests; no database changes."""
import unittest
from unittest.mock import patch
from decimal import Decimal
from types import SimpleNamespace
from qcmc_logic.dynamic_reorder_monitor import approved_result


class TestApprovedMonitoring(unittest.TestCase):
    def setUp(self):
        self.bom=patch("qcmc_logic.dynamic_reorder_replenishment.manufacturing_readiness",return_value=("Ready","","BOM-I")).start()
        self.addCleanup(patch.stopall)

    def state(self, projected=500, qty=1000, requests=None):
        history=SimpleNamespace(name="APPROVED",company="Co",recommended_level=800,recommended_qty=1000)
        return history,SimpleNamespace(name="I"),None,"Manufacture",Decimal(projected),Decimal(qty),requests or []

    def test_missing_bom_shows_shortage_but_blocks_request(self):
        self.bom.return_value=("BOM Required","Missing BOM",None)
        result=approved_result({},self.state(),True)
        self.assertEqual(result["monitor_status"],"BOM Required")
        self.assertEqual(result["manufacturing_readiness"],"BOM Required")
        self.assertFalse(result["can_create_request"])
        self.assertEqual(result["candidate_qty"],1000)

    def test_open_request_retains_priority_with_missing_bom(self):
        self.bom.return_value=("BOM Required","Missing BOM",None)
        result=approved_result({},self.state(requests=["MR1"]),True)
        self.assertEqual(result["monitor_status"],"Open Material Request")
        self.assertEqual(result["manufacturing_readiness"],"BOM Required")
        self.assertIn("Missing BOM",result["monitor_reason"])

    def test_approved_values_replace_preview(self):
        result=approved_result(dict(reorder_level=9999,reorder_qty=8888),self.state(),True)
        self.assertEqual(result["reorder_level"],800)
        self.assertEqual(result["reorder_qty"],1000)
        self.assertEqual(result["approval"],"APPROVED")
        self.assertEqual(result["monitor_status"],"Replenishment Required")
        self.assertTrue(result["can_create_request"])

    def test_disabled_mode_still_displays_shortage(self):
        result=approved_result({},self.state(),False)
        self.assertEqual(result["monitor_status"],"Replenishment Required")
        self.assertFalse(result["can_create_request"])
        self.assertEqual(result["candidate_qty"],1000)

    def test_open_request_prevents_new_request(self):
        result=approved_result({},self.state(requests=["MR1"]),True)
        self.assertEqual(result["monitor_status"],"Open Material Request")
        self.assertFalse(result["can_create_request"])
        self.assertEqual(result["candidate_qty"],0)

    def test_transfer_monitor_blocks_insufficient_source_stock(self):
        h,item,policy,_,projected,qty,requests=self.state()
        with patch("qcmc_logic.dynamic_reorder_transfer.transfer_readiness",return_value=("Insufficient Source Stock","Short","A")) as ready:
            result=approved_result({},(h,item,policy,"Transfer",projected,qty,requests),True)
            self.assertEqual(result["monitor_status"],"Insufficient Source Stock")
            self.assertFalse(result["can_create_request"])
            self.assertEqual(result["transfer_source_warehouse"],"A")
            ready.assert_called_once_with(h,item.name,qty,read_only=True)

    def test_healthy_stock(self):
        result=approved_result({},self.state(projected=5000,qty=0),True)
        self.assertEqual(result["monitor_status"],"Above Reorder Level")
        self.assertFalse(result["can_create_request"])
