"""Posted stock movement semantics, including both Warehouse Transfer posting models."""
import unittest
from datetime import date
from decimal import Decimal
from unittest.mock import patch, MagicMock
from qcmc_logic import dynamic_reorder_demand as d


class TestConsolidatedDemand(unittest.TestCase):
    def event(self, **values):
        return dict(id="1",item_code="I",warehouse="A",posting_date=date(2026,10,5),actual_qty=-10,
                    source="A",target="Outside",source_type="Delivery Note",docstatus=1,is_cancelled=0,is_return=0) | values

    def aggregate(self, events, sources=None, deduct=True):
        return d.aggregate_movements(events,["A","B"],sources or d.DEMAND_SOURCES,deduct)

    def test_all_four_sources_and_configuration(self):
        events=[self.event(id=str(i),source_type=s) for i,s in enumerate(d.DEMAND_SOURCES)]
        data=self.aggregate(events)
        self.assertEqual(data[("I","A",date(2026,10,1))]["gross"],40)
        for source in d.DEMAND_SOURCES:
            data=self.aggregate(events,[source])
            self.assertEqual(data[("I","A",date(2026,10,1))]["net"],10)
        self.assertEqual(d.aggregate_movements(events,["A","B"],[],True),{})

    def test_internal_movements_and_inbound_supply_are_not_demand(self):
        for source in d.DEMAND_SOURCES:
            with self.subTest(source=source):
                self.assertEqual(self.aggregate([self.event(source_type=source,target="B")]),{})
                self.assertEqual(self.aggregate([self.event(source_type=source,actual_qty=10,source="Outside",target="A")]),{})

    def test_returns_for_each_source_and_toggle(self):
        for source in d.DEMAND_SOURCES:
            events=[self.event(source_type=source),self.event(id="return",source_type=source,
                    is_return=1,source="Outside",target="A",actual_qty=3)]
            with self.subTest(source=source):
                row=self.aggregate(events)[("I","A",date(2026,10,1))]
                self.assertEqual(row,{"gross":Decimal(10),"returns":Decimal(3),"net":Decimal(7)})
                self.assertEqual(self.aggregate(events,deduct=False)[("I","A",date(2026,10,1))]["net"],10)

    def test_cancelled_draft_unscoped_and_duplicate_sle(self):
        events=[self.event(),self.event(),self.event(id="cancelled",is_cancelled=1),
                self.event(id="draft",docstatus=0),self.event(id="other",warehouse="Else")]
        self.assertEqual(self.aggregate(events)[("I","A",date(2026,10,1))]["gross"],10)

    def test_negative_month_retained_for_calculator_review(self):
        data=self.aggregate([self.event(is_return=1,actual_qty=20,source="Outside",target="A")])
        self.assertEqual(data[("I","A",date(2026,10,1))]["net"],-20)

    def test_sql_loader_is_bounded_and_uses_transfer_deduplication(self):
        import frappe
        with patch.object(frappe,"db",MagicMock()) as db, patch.object(frappe,"get_meta") as meta:
            db.sql.return_value=[]
            db.exists.return_value=True
            sql=db.sql
            meta.return_value.has_field.return_value=False
            d.monthly_demand("Co",["A","B"],["I"],date(2026,10,1),date(2026,10,31),sources=d.DEMAND_SOURCES)
            statements=" ".join(c.args[0] for c in sql.call_args_list)
            self.assertIn("NOT EXISTS",statements)
            self.assertIn("source_stock_entry",statements)
            self.assertIn("target_stock_entry",statements)
            self.assertIn("voucher_detail_no",statements)
            self.assertNotIn("Sales Invoice",statements)
            for call in sql.call_args_list:
                self.assertIn("Co",call.args[1])
                self.assertIn(("A","B"),call.args[1])
                self.assertIn(("I",),call.args[1])
