"""WRR receipts must contribute alongside allocations and physical counts."""
import unittest
from unittest.mock import patch
import frappe
from qcmc_logic.api import stock_reconciliation as stock


class TestWRRLocationBalance(unittest.TestCase):
    def quantity(self, count, allocation, receipt, legacy=0):
        with (patch.object(frappe.db, 'sql', side_effect=[
            [frappe._dict(physical_count=count, counted_at='2026-11-01' if count is not None else None)],
            [frappe._dict(quantity=allocation, row_count=int(bool(allocation)))],
            [(0,)], [(receipt,)],
        ]), patch.object(stock, 'get_dimension_stock_balance', return_value=legacy),
              patch('qcmc_logic.warehouse_transfer_out_balance.get_out_movements', return_value=[]),
              patch('qcmc_logic.delivery_note_pick_list.get_delivery_note_out_movements', return_value=[]),
              patch('qcmc_logic.stock_entry_out_balance.get_out_movements', return_value=[])):
            return stock._current_inventory_quantity('ITEM', 'WH', 'LOC')

    def test_receipt_adds_to_allocated_stock(self):
        self.assertEqual(self.quantity(None, 40000, 10000), 50000)

    def test_receipt_after_count_adds_to_counted_stock(self):
        self.assertEqual(self.quantity(40000, 0, 10000), 50000)

    def test_supplier_return_reduces_stock(self):
        self.assertEqual(self.quantity(None, 40000, -10000), 30000)

    def test_legacy_ledger_fallback_does_not_double_count_receipt(self):
        self.assertEqual(self.quantity(None, 0, 10000, legacy=10000), 10000)


def run_tests():
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(TestWRRLocationBalance))
    if not result.wasSuccessful():
        raise AssertionError('WRR location balance tests failed')
    return {'tests_run': result.testsRun, 'successful': True}
