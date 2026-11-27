"""Transfer readiness tests with mocked database boundaries."""
import unittest
from unittest.mock import patch, MagicMock
from decimal import Decimal
import frappe
from qcmc_logic import dynamic_reorder_transfer as t


class TestTransferReadiness(unittest.TestCase):
    def row(self, province=0, **kwargs):
        row = frappe._dict(company="Co", disabled=0, is_group=0,
                           warehouse_type="Finished Goods", custom_is_province=province)
        row.update(kwargs)
        return row

    def check(self, source="A", destination="B", scope=("B",)):
        return t.validate_transfer_source("Co",source,destination,scope)

    def test_valid_source(self):
        with patch.object(frappe,"db",MagicMock()) as db, patch.object(t,"_can_serve_material_requests",return_value=True):
            db.get_value.side_effect=[self.row(),self.row(1)]
            self.assertEqual(self.check(),"A")

    def test_missing_or_overlapping_source(self):
        with patch.object(frappe,"throw",side_effect=lambda msg: (_ for _ in ()).throw(ValueError(msg))), patch.object(frappe,"db",MagicMock()) as db:
            for source, scope in ((None,("B",)),("B",("B",)),("A",("A","B"))):
                with self.assertRaises(ValueError):
                    self.check(source,scope=scope)
            db.get_value.assert_not_called()

    def test_wrong_company_disabled_group_provincial_or_non_fg_source(self):
        invalid = [self.row(company="Other"),self.row(disabled=1),self.row(is_group=1),
                   self.row(1),self.row(warehouse_type="Raw Material")]
        with patch.object(frappe,"throw",side_effect=lambda msg: (_ for _ in ()).throw(ValueError(msg))), patch.object(frappe,"db",MagicMock()) as db, patch.object(t,"_can_serve_material_requests",return_value=True):
            for source in invalid:
                db.get_value.side_effect=[source,self.row(1)]
                with self.assertRaises(ValueError):
                    self.check()

    def test_non_provincial_target_and_unapproved_serving_source(self):
        with patch.object(frappe,"throw",side_effect=lambda msg: (_ for _ in ()).throw(ValueError(msg))), patch.object(frappe,"db",MagicMock()) as db, patch.object(t,"_can_serve_material_requests",return_value=False):
            for target in (self.row(),self.row(1)):
                db.get_value.side_effect=[self.row(),target]
                with self.assertRaises(ValueError):
                    self.check()

    def test_available_quantity_excludes_incoming_and_outgoing_commitments(self):
        row = dict(actual_qty=100, projected_qty=150, reserved_qty=20,
                   reserved_qty_for_production=5, reserved_qty_for_sub_contract=5,
                   reserved_qty_for_production_plan=0)
        self.assertEqual(t.available_source_quantity(row,[dict(stock_qty=10)]),60)
        row["projected_qty"]=40
        self.assertEqual(t.available_source_quantity(row,[dict(stock_qty=10)]),30)
        self.assertEqual(t.available_source_quantity(row,[dict(stock_qty=200)]),0)
        self.assertEqual(t.available_source_quantity(None,[]),0)

    def test_readiness_uses_current_locks_and_blocks_shortage(self):
        history = frappe._dict(company="Co",warehouse="B",
            details='{"transfer_source_warehouse":"A","warehouses":["B"]}')
        with patch.object(t,"validate_transfer_source",return_value="A"), patch.object(frappe,"db",MagicMock()) as db:
            db.sql.side_effect=[[dict(actual_qty=100,projected_qty=100)],[dict(stock_qty=20)]]
            self.assertEqual(t.transfer_readiness(history,"I",81,read_only=False)[0],"Insufficient Source Stock")
            self.assertTrue(all("FOR UPDATE" in c.args[0] for c in db.sql.call_args_list))
            db.sql.side_effect=[[dict(actual_qty=100,projected_qty=100)],[dict(stock_qty=20)]]
            self.assertEqual(t.transfer_readiness(history,"I",80),("Ready","","A"))
            db.commit.assert_not_called()
