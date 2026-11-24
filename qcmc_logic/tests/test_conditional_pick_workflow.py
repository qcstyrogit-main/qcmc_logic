"""Mocked regression guards for conditional warehouse workflows; no stock posting."""
import unittest
from unittest.mock import patch
import frappe
from qcmc_logic import warehouse_transfer_allocation as wt
from qcmc_logic import stock_entry_material_issue_pick_list as issue
from qcmc_logic import stock_entry_manufacture_pick_list as manufacture
from qcmc_logic import picking_status
from qcmc_logic.api import wts_picker_scanner as scanner
from qcmc_logic.customs import warehouse_transfer_events as events


class TestConditionalPickWorkflow(unittest.TestCase):
    def test_active_leaf_detection(self):
        with patch.object(frappe.db, "exists", return_value="BIN") as exists:
            self.assertTrue(wt.warehouse_has_storage_locations("WH"))
            exists.assert_called_once_with("Storage Location", {
                "custom_warehouse": "WH", "disabled": 0, "is_group": 0,
            })
        self.assertFalse(wt.warehouse_has_storage_locations(None))

    def test_target_without_locations_disables_allocation(self):
        doc = frappe._dict(docstatus=0, target_warehouse="WH",
                           custom_apply_putaway_rule=1)
        with patch.object(wt, "warehouse_has_storage_locations", return_value=False):
            wt.prepare_transfer(doc)
        self.assertEqual(doc.custom_storage_allocation_enabled, 0)
        self.assertEqual(doc.custom_apply_putaway_rule, 0)

    def test_target_with_locations_keeps_manual_selection(self):
        for checked in (0, 1):
            doc = frappe._dict(docstatus=0, target_warehouse="WH",
                               custom_apply_putaway_rule=checked)
            with patch.object(wt, "warehouse_has_storage_locations", return_value=True):
                wt.prepare_transfer(doc)
            self.assertEqual(doc.custom_storage_allocation_enabled, 1)
            self.assertEqual(doc.custom_apply_putaway_rule, checked)

    def test_source_without_locations_can_transfer(self):
        doc = frappe._dict(transfer_type="Warehouse Transfer", source_warehouse="WH",
                           transfer_items=[frappe._dict(idx=1, issued_qty=5)])
        with patch.object(wt, "warehouse_has_storage_locations", return_value=False):
            events.require_submitted_pick_list_before_transfer(doc)

    def test_source_with_locations_requires_pick(self):
        doc = frappe._dict(transfer_type="Warehouse Transfer", source_warehouse="WH",
                           transfer_items=[frappe._dict(idx=1, issued_qty=5)])
        with patch.object(wt, "warehouse_has_storage_locations", return_value=True):
            with self.assertRaises(frappe.ValidationError):
                events.require_submitted_pick_list_before_transfer(doc)

    def test_mixed_stock_entry_requires_pick(self):
        doc = frappe._dict(items=[frappe._dict(qty=2, s_warehouse="PLAIN"),
                                  frappe._dict(qty=3, s_warehouse="BIN")])
        for module in (issue, manufacture):
            with patch.object(module, "warehouse_has_storage_locations", side_effect=lambda w: w == "BIN"):
                self.assertTrue(module.requires_source_picking(doc))
                doc["items"][1].qty = 0
                self.assertFalse(module.requires_source_picking(doc))
                doc["items"][1].qty = 3

    def test_scanner_fallback_requires_no_existing_allocation(self):
        doc = frappe._dict(name="WTS", target_warehouse="WH", custom_storage_allocation_enabled=0)
        with patch.object(scanner, "warehouse_has_storage_locations", return_value=False):
            with patch.object(scanner, "linked_allocations", return_value=[]):
                self.assertEqual(scanner.validate_scanner_allocations(doc), [])
                self.assertFalse(scanner._allocation_result(doc)["allocation_required"])
                self.assertTrue(scanner._allocation_result(doc)["allocation_ready"])
            with patch.object(scanner, "linked_allocations", return_value=[frappe._dict(docstatus=0, locations=[1])]):
                self.assertFalse(scanner.allocation_not_required(doc))
        with patch.object(scanner, "warehouse_has_storage_locations", return_value=True):
            self.assertFalse(scanner.allocation_not_required(doc))


def run_tests():
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(TestConditionalPickWorkflow))
    if not result.wasSuccessful():
        raise AssertionError("Conditional warehouse workflow tests failed")
    return {"tests_run": result.testsRun, "successful": True}
