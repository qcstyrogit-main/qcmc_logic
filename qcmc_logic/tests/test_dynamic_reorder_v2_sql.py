"""Execute demand SQL against disposable SQLite tables, never a Frappe site.

Only DB-API parameter expansion differs from MariaDB; production SELECTs are
executed unchanged, including joins, EXISTS deduplication and sign matching.
"""
import sqlite3
import unittest
from datetime import date
from unittest.mock import patch, MagicMock
import frappe
from qcmc_logic.dynamic_reorder_demand import monthly_demand, DEMAND_SOURCES


class TestDemandSQL(unittest.TestCase):
    def setUp(self):
        self.connection=sqlite3.connect(":memory:")
        self.addCleanup(self.connection.close)
        self.connection.row_factory=sqlite3.Row
        self.connection.create_function("SIGN",1,lambda n:(n>0)-(n<0))
        for name,cols in {
            "Stock Ledger Entry":"name TEXT, item_code TEXT, warehouse TEXT, posting_date TEXT, actual_qty REAL, is_cancelled INTEGER DEFAULT 0, company TEXT DEFAULT 'Co', voucher_type TEXT, voucher_no TEXT, voucher_detail_no TEXT",
            "Delivery Note":"name TEXT, docstatus INTEGER DEFAULT 1, is_return INTEGER DEFAULT 0, is_internal_customer INTEGER DEFAULT 0",
            "Stock Entry":"name TEXT, docstatus INTEGER DEFAULT 1, is_return INTEGER DEFAULT 0, stock_entry_type TEXT, purpose TEXT",
            "Stock Entry Detail":"name TEXT, parent TEXT, s_warehouse TEXT, t_warehouse TEXT",
            "Warehouse Transfer":"name TEXT, docstatus INTEGER DEFAULT 1, transfer_type TEXT, source_stock_entry TEXT, target_stock_entry TEXT, source_warehouse TEXT, target_warehouse TEXT",
        }.items():
            self.connection.execute(f"CREATE TABLE `tab{name}` ({cols})")
        self.counter=0

    def insert(self,dt,**fields):
        names=",".join(fields)
        markers=",".join("?" for _ in fields)
        self.connection.execute(f"INSERT INTO `tab{dt}` ({names}) VALUES ({markers})",tuple(fields.values()))

    def sle(self,voucher,number,qty=-10,warehouse="A",detail=None,**fields):
        self.counter+=1
        self.insert("Stock Ledger Entry",name=str(self.counter),item_code="I",warehouse=warehouse,
                    posting_date="2026-10-05",actual_qty=qty,voucher_type=voucher,voucher_no=number,
                    voucher_detail_no=detail,**fields)

    def query(self,statement,params,as_dict=True):
        parts=statement.split("%s"); sql=parts[0]; values=[]
        for param,tail in zip(params,parts[1:]):
            if isinstance(param,tuple):
                sql += "("+",".join("?" for _ in param)+")"; values.extend(param)
            else:
                sql += "?"; values.append(str(param) if isinstance(param,date) else param)
            sql += tail
        return [frappe._dict(dict(row)) for row in self.connection.execute(sql,values)]

    def demand(self,sources=None):
        db=MagicMock(); db.sql.side_effect=self.query; db.exists.return_value=True
        meta=MagicMock(); meta.has_field.side_effect=lambda field: field=="is_internal_customer"
        with patch.object(frappe,"db",db),patch.object(frappe,"get_meta",return_value=meta):
            return monthly_demand("Co",["A","B"],["I"],date(2026,10,1),date(2026,10,31),sources=sources)

    def total(self,field="net",sources=None):
        return sum(row[field] for row in self.demand(sources).values())

    def transfer(self,name="WT",source="A",target="Outside",kind=DEMAND_SOURCES[2],**fields):
        self.insert("Warehouse Transfer",name=name,source_warehouse=source,target_warehouse=target,transfer_type=kind,**fields)

    def entry(self,name="SE",source="A",target="Outside",kind=DEMAND_SOURCES[2],**fields):
        self.insert("Stock Entry",name=name,stock_entry_type=kind,purpose=kind,**fields)
        self.insert("Stock Entry Detail",name=name+"-row",parent=name,s_warehouse=source,t_warehouse=target)
        self.sle("Stock Entry",name,detail=name+"-row")

    def test_delivery_returns_internal_customer_and_cancelled_sle(self):
        self.insert("Delivery Note",name="DN")
        self.sle("Delivery Note","DN",qty=-20)
        self.sle("Delivery Note","DN",qty=-100,is_cancelled=1)
        self.insert("Delivery Note",name="Return",is_return=1)
        self.sle("Delivery Note","Return",qty=4,warehouse="B")
        self.insert("Delivery Note",name="Internal",is_internal_customer=1)
        self.sle("Delivery Note","Internal",qty=-100)
        self.assertEqual(self.total(),16)
        self.assertEqual(self.total("gross"),20)

    def test_four_sources_configuration_and_manufacturing_return(self):
        self.insert("Delivery Note",name="DN"); self.sle("Delivery Note","DN")
        for index,source in enumerate(DEMAND_SOURCES[1:]):
            self.entry(name="SE"+str(index),kind=source)
        self.entry(name="Return",source="Outside",target="A",kind=DEMAND_SOURCES[1],is_return=1)
        self.sle("Stock Entry","Return",qty=3,detail="Return-row")
        self.assertEqual(self.total(),37)
        for source,expected in zip(DEMAND_SOURCES,(10,7,10,10)):
            self.assertEqual(self.total(sources=[source]),expected)

    def test_direct_transfer_deduplicates_linked_source_entry(self):
        self.transfer(source_stock_entry="SE")
        self.entry(kind="Warehouse Transfer",target=None)
        self.sle("Warehouse Transfer","WT")
        self.assertEqual(self.total(),10)

    def test_legacy_transfer_uses_linked_entry_without_direct_ledger(self):
        self.transfer(source_stock_entry="SE")
        self.entry(kind="Warehouse Transfer",target=None)
        self.assertEqual(self.total(),10)

    def test_internal_transfer_excluded_for_both_posting_models(self):
        self.transfer(target="B",source_stock_entry="SE")
        self.entry(kind="Warehouse Transfer",target=None)
        self.sle("Warehouse Transfer","WT")
        self.sle("Warehouse Transfer","WT",qty=10,warehouse="B")
        self.assertEqual(self.total(),0)

    def test_cancelled_transfer_does_not_count_linked_entry(self):
        self.transfer(source_stock_entry="SE",docstatus=2)
        self.entry(kind="Warehouse Transfer",target=None)
        self.sle("Warehouse Transfer","WT")
        self.assertEqual(self.total(),0)

    def test_positive_transfer_receipt_is_supply_not_assumed_return(self):
        self.transfer(source="Outside",target="A",target_stock_entry="SE")
        self.insert("Stock Entry",name="SE",stock_entry_type="Warehouse Transfer Receipt",purpose="Material Receipt")
        self.insert("Stock Entry Detail",name="row",parent="SE",t_warehouse="A")
        self.sle("Stock Entry","SE",qty=10,detail="row")
        self.sle("Warehouse Transfer","WT",qty=10)
        self.assertEqual(self.total(),0)

    def test_provincial_and_nonapproved_generic_transfer(self):
        self.transfer(kind=DEMAND_SOURCES[3]); self.sle("Warehouse Transfer","WT")
        self.transfer(name="Generic",kind="Warehouse Transfer"); self.sle("Warehouse Transfer","Generic")
        self.assertEqual(self.total(),10)
