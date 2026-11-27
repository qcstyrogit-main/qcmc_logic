"""Replenishment unit tests; database writes are mocked."""
import unittest
from decimal import Decimal
from unittest.mock import patch, MagicMock
from datetime import date
import frappe
from qcmc_logic import dynamic_reorder_replenishment as r


class TestReplenishment(unittest.TestCase):
    def test_automatic_mode_requires_all_global_controls(self):
        settings=frappe._dict(enabled=1,preview_only=0,automatic_update_enabled=0,replenishment_mode="Automatic Draft")
        with patch.object(frappe,"get_single",return_value=settings),patch.object(frappe,"db",MagicMock()) as db:
            db.get_single_value.return_value=0
            self.assertTrue(r.automatic_enabled())
            for field,value in (("enabled",0),("preview_only",1),("automatic_update_enabled",1),("replenishment_mode","Manual Draft")):
                old=settings[field]
                settings[field]=value
                self.assertFalse(r.automatic_enabled())
                settings[field]=old
            db.get_single_value.return_value=1
            self.assertFalse(r.automatic_enabled())

    def test_scheduler_not_installed_no_writes(self):
        with patch.object(frappe,"db",MagicMock()) as db,patch.object(r,"_create_draft") as create:
            db.exists.return_value=False
            self.assertEqual(r.scheduled_drafts()["status"],"Not Installed")
            create.assert_not_called()
            db.commit.assert_not_called()

    def test_manual_trigger_requires_admin(self):
        with patch.object(r,"require_admin",side_effect=PermissionError),patch.object(r,"_run_batch") as run:
            with self.assertRaises(PermissionError):
                r.run_now("M")
            run.assert_not_called()

    def test_manual_trigger_forwards_mapping(self):
        with patch.object(r,"require_admin"),patch.object(r,"_run_batch") as run:
            r.run_now("M")
            run.assert_called_once_with(automatic=False,mapping="M")

    def test_scheduled_trigger_shares_engine(self):
        with patch.object(r,"_run_batch") as run:
            r.scheduled_drafts()
            run.assert_called_once_with(automatic=True)

    def test_manual_mode_controls(self):
        settings=frappe._dict(enabled=1,preview_only=0,automatic_update_enabled=0,replenishment_mode="Manual Draft")
        with patch.object(frappe,"get_single",return_value=settings),patch.object(frappe,"db",MagicMock()) as db:
            db.get_single_value.return_value=0
            self.assertTrue(r.manual_enabled())
            settings.replenishment_mode="Automatic Draft"
            self.assertTrue(r.manual_enabled())
            settings.replenishment_mode="Disabled"
            self.assertFalse(r.manual_enabled())
            settings.replenishment_mode="Manual Draft"
            settings.preview_only=1
            self.assertFalse(r.manual_enabled())

    def test_above_level(self):
        self.assertEqual(r.candidate_quantity(800.01,1000,25000),0)

    def test_equal_level(self):
        self.assertEqual(r.candidate_quantity(800.01,1000,800.01),1000)

    def test_deficiency_exceeds_roq(self):
        self.assertEqual(r.candidate_quantity(800.01,1000,-500),1301)

    def test_zero_configuration(self):
        self.assertEqual(r.candidate_quantity(0,0,-500),0)

    def test_invalid_configuration(self):
        with self.assertRaises(ValueError):
            r.candidate_quantity(-1,1000,0)

    def test_decimal_precision(self):
        self.assertEqual(r.candidate_quantity(10.123,2,0,2),Decimal("10.13"))

    def state(self, projected=800, qty=1000, requests=None):
        h=MagicMock(name="History")
        h.name="H"; h.company="Co"; h.mapping="M"; h.warehouse="MC1"
        item=frappe._dict(name="I",item_name="Item",description="Item",stock_uom="PCS")
        policy=frappe._dict(lead_time=7)
        return h,item,policy,"Manufacture",Decimal(projected),Decimal(qty),requests or []

    def test_open_request_blocks_creation(self):
        with patch.object(r,"approved_state",return_value=self.state(requests=["MR1"])),patch.object(frappe,"new_doc") as new:
            self.assertEqual(r._create_draft("H")["status"],"Open Material Request")
            new.assert_not_called()

    def test_healthy_stock_blocks_creation(self):
        with patch.object(r,"approved_state",return_value=self.state(projected=25000,qty=0)),patch.object(frappe,"new_doc") as new:
            self.assertEqual(r._create_draft("H")["status"],"Above Reorder Level")
            new.assert_not_called()

    def test_draft_created_not_submitted(self):
        state=self.state()
        with patch.object(r,"approved_state",return_value=state),patch.object(r,"manufacturing_readiness",return_value=("Ready","","BOM-I")),patch.object(r,"business_date",return_value=date(2026,11,25)),patch.object(frappe,"get_meta") as meta,patch.object(frappe,"new_doc") as new:
            meta.return_value.has_field.return_value=True
            mr=new.return_value
            mr.name="MR1"
            result=r._create_draft("H")
            self.assertEqual(result["status"],"Draft Created")
            self.assertEqual(result["warehouse"],"MC1")
            self.assertEqual(mr.update.call_args.args[0]["custom_replenishment_history"],"H")
            self.assertEqual(mr.update.call_args.args[0]["set_warehouse"],"MC1")
            self.assertEqual(mr.append.call_args.args[1]["warehouse"],"MC1")
            self.assertEqual(mr.append.call_args.args[1]["qty"],1000)
            mr.insert.assert_called_once()
            mr.submit.assert_not_called()
            state[0].add_comment.assert_called_once()

    def test_missing_bom_blocks_manual_and_scheduled_creation(self):
        for automatic in (False,True):
            with patch.object(r,"approved_state",return_value=self.state()),patch.object(r,"manufacturing_readiness",return_value=("BOM Required","Missing BOM",None)),patch.object(frappe,"new_doc") as new:
                result=r._create_draft("H",automatic=automatic)
                self.assertEqual(result["status"],"BOM Required")
                new.assert_not_called()

    def test_purchase_does_not_query_bom(self):
        with patch.object(frappe,"db",MagicMock()) as db:
            self.assertEqual(r.manufacturing_readiness("I","Co","Purchase"),("Not Applicable","",None))
            db.get_value.assert_not_called()

    def test_default_bom_readiness(self):
        with patch.object(frappe,"db",MagicMock()) as db:
            db.get_value.return_value=frappe._dict(name="BOM-I",company="Co",is_active=1)
            self.assertEqual(r.manufacturing_readiness("I","Co","Manufacture"),("Ready","","BOM-I"))
            self.assertEqual(db.get_value.call_args.args[1],dict(item="I",is_default=1,docstatus=1))
            db.get_value.return_value=frappe._dict(name="BOM-I",company="Other",is_active=1)
            self.assertEqual(r.manufacturing_readiness("I","Co","Manufacture")[0],"BOM Required")
            db.get_value.return_value=frappe._dict(name="BOM-I",company="Co",is_active=0)
            self.assertEqual(r.manufacturing_readiness("I","Co","Manufacture")[0],"BOM Required")
            db.get_value.return_value=None
            self.assertEqual(r.manufacturing_readiness("I","Co","Manufacture")[0],"BOM Required")

    def test_variant_bom_must_be_submitted(self):
        with patch.object(frappe,"db",MagicMock()) as db:
            db.get_value.side_effect=[None,"TEMPLATE",frappe._dict(name="BOM-T",company="Co",is_active=1,docstatus=0)]
            self.assertEqual(r.manufacturing_readiness("I","Co","Manufacture")[0],"BOM Required")
            db.get_value.side_effect=[None,"TEMPLATE",frappe._dict(name="BOM-T",company="Co",is_active=1,docstatus=1)]
            self.assertEqual(r.manufacturing_readiness("I","Co","Manufacture"),("Ready","","BOM-T"))

    def test_api_requires_admin(self):
        with patch.object(r,"require_admin",side_effect=PermissionError),patch.object(r,"_create_draft") as create:
            with self.assertRaises(PermissionError):
                r.create_draft("H")
            create.assert_not_called()
