import unittest
import inspect
from unittest.mock import patch
from types import SimpleNamespace

import frappe

from qcmc_logic.api.manufacturing_scanner import (
	_apply_confirmations,
	_document_id,
	_material_transfer_doc,
	submit_material_transfer,
)
from qcmc_logic.api.stock_entry_scanner import ScannerAPIError


class TestManufacturingScannerContract(unittest.TestCase):
	def test_qr_ids_are_normalized(self):
		self.assertEqual(_document_id("/app/job-card/JC-0001"), "JC-0001")
		self.assertEqual(
			_document_id('{"type":"work_order","work_order_id":"MFG-WO-0001"}'),
			"MFG-WO-0001",
		)

	def test_transfer_uses_standard_stock_entry_and_job_card(self):
		row = frappe._dict(item_code="RM", qty=2, s_warehouse="", t_warehouse="")
		doc = SimpleNamespace(items=[row])
		doc.set_stock_entry_type = lambda: None
		doc.get_items = lambda: None
		jc = frappe._dict(name="JC", semi_fg_bom="", bom_no="BOM", for_quantity=5, transferred_qty=1, source_warehouse="RAW", wip_warehouse="WIP")
		wo = frappe._dict(name="WO", company="C", bom_no="BOM", source_warehouse="RAW", wip_warehouse="WIP")
		with patch("frappe.new_doc", return_value=doc):
			result = _material_transfer_doc(jc, wo)
		self.assertEqual((result.purpose, result.job_card, result.fg_completed_qty), ("Material Transfer for Manufacture", "JC", 4))
		self.assertEqual((row.s_warehouse, row.t_warehouse), ("RAW", "WIP"))

	def test_confirmation_requires_exact_erp_rows(self):
		row = frappe._dict(item_code="RM", s_warehouse="RAW", t_warehouse="WIP", uom="PC", qty=2)
		doc = SimpleNamespace(items=[row])
		_apply_confirmations(doc, [{"item_code":"RM", "source_warehouse":"RAW", "target_warehouse":"WIP", "uom":"PC", "quantity":2}])
		with self.assertRaises(ScannerAPIError):
			_apply_confirmations(doc, [{"item_code":"RM", "source_warehouse":"OTHER", "target_warehouse":"WIP", "uom":"PC", "quantity":2}])

	def test_operation_is_explicit(self):
		with patch("qcmc_logic.api.manufacturing_scanner._auth", return_value="Administrator"):
			result = submit_material_transfer("JC", "wrong", "id", [])
		self.assertEqual(result["error_code"], "INVALID_OPERATION")

	def test_internal_submission_record_bypasses_caller_doctype_permission(self):
		source = inspect.getsource(submit_material_transfer)
		self.assertIn("insert(ignore_permissions=True)", source)


def run_test_suite():
	suite = unittest.defaultTestLoader.loadTestsFromTestCase(TestManufacturingScannerContract)
	result = unittest.TextTestRunner(verbosity=2).run(suite)
	if not result.wasSuccessful():
		raise AssertionError("Manufacturing scanner tests failed")
	return {"tests_run": result.testsRun}
