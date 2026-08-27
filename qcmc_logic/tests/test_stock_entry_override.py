import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace

import frappe

from qcmc_logic.overrides.stock_entry import CustomStockEntry, _sync_tracked_final_work_order


class TestManufactureDraftPutawayValidation(unittest.TestCase):
	def test_empty_stock_entry_can_validate_as_draft(self):
		doc = SimpleNamespace(items=[], _action="save")
		doc.get = lambda fieldname: getattr(doc, fieldname, None)
		doc.validate_posting_time = Mock()
		doc.validate_purpose = Mock()
		doc.set_purpose_for_stock_entry = Mock()
		CustomStockEntry.validate(doc)
		doc.validate_posting_time.assert_called_once()

	def test_empty_stock_entry_cannot_be_submitted(self):
		doc = SimpleNamespace(items=[], _action="submit")
		doc.get = lambda fieldname: getattr(doc, fieldname, None)
		with self.assertRaises(frappe.EmptyTableError):
			CustomStockEntry.validate(doc)

	def test_unallocated_manufacture_draft_defers_capacity_validation(self):
		doc = SimpleNamespace(
			purpose="Manufacture",
			_action="save",
			items=[frappe._dict(is_finished_item=1, t_warehouse="FG", putaway_rule="", to_location="")],
		)
		with patch("qcmc_logic.overrides.stock_entry.validate_dimension_putaway_capacity") as validate:
			CustomStockEntry.validate_putaway_capacity(doc)
		validate.assert_not_called()

	def test_manual_submit_and_allocated_draft_still_validate_capacity(self):
		for action, rule in (("submit", ""), ("save", "PUT-1")):
			doc = SimpleNamespace(
				purpose="Manufacture",
				_action=action,
				items=[frappe._dict(is_finished_item=1, t_warehouse="FG", putaway_rule=rule, to_location="")],
			)
			with patch("qcmc_logic.overrides.stock_entry.validate_dimension_putaway_capacity") as validate:
				CustomStockEntry.validate_putaway_capacity(doc)
			validate.assert_called_once_with(doc)

	def test_tracked_final_output_updates_work_order_quantity_and_status(self):
		work_order = SimpleNamespace(
			track_semi_finished_goods=1,
			production_item="FG",
			get_transferred_or_manufactured_qty=Mock(return_value=50),
			db_set=Mock(),
			set_process_loss_qty=Mock(),
			run_method=Mock(),
		)
		stock_entry = SimpleNamespace(
			work_order="WO-1", purpose="Manufacture",
			items=[frappe._dict(is_finished_item=1, item_code="FG")],
		)
		stock_entry.get = lambda fieldname: getattr(stock_entry, fieldname, None)
		with patch("frappe.get_doc", return_value=work_order):
			_sync_tracked_final_work_order(stock_entry)
		work_order.db_set.assert_called_once_with("produced_qty", 50)
		work_order.set_process_loss_qty.assert_called_once()
		self.assertEqual(work_order.run_method.call_args_list[-1].args, ("update_status",))

	def test_untracked_or_nonfinal_output_is_not_custom_synced(self):
		for tracked, item_code in ((0, "FG"), (1, "OTHER")):
			work_order = SimpleNamespace(track_semi_finished_goods=tracked, production_item="FG")
			stock_entry = SimpleNamespace(
				work_order="WO-1", purpose="Manufacture",
				items=[frappe._dict(is_finished_item=1, item_code=item_code)],
			)
			stock_entry.get = lambda fieldname: getattr(stock_entry, fieldname, None)
			with patch("frappe.get_doc", return_value=work_order):
				_sync_tracked_final_work_order(stock_entry)
			self.assertFalse(hasattr(work_order, "produced_qty"))


def run_test_suite():
	suite = unittest.defaultTestLoader.loadTestsFromTestCase(TestManufactureDraftPutawayValidation)
	result = unittest.TextTestRunner(verbosity=2).run(suite)
	if not result.wasSuccessful():
		raise AssertionError("Stock Entry override tests failed")
	return {"tests_run": result.testsRun}
