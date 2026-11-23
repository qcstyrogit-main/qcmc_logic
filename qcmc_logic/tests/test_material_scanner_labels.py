"""QR defaults and access regressions, with no site or database writes."""
from unittest import TestCase
from unittest.mock import MagicMock, call, patch

import frappe

from qcmc_logic.api import material_scanner_labels as labels


class TestMaterialScannerLabels(TestCase):
	def setUp(self):
		self.item = MagicMock()
		self.item.name = self.item.item_code = "EFB10"
		self.item.item_name = "Test Item"
		self.item.stock_uom = "Nos"
		self.item.is_stock_item = 1
		self.item.disabled = 0
		self.item.get.return_value = 500
		for patcher in (
			patch.object(labels.frappe, "get_doc", return_value=self.item),
			patch.object(labels, "generate_qr", return_value="qr-image"),
			patch.object(labels, "_", side_effect=lambda value: value),
			patch.object(labels.frappe, "throw", side_effect=ValueError),
		):
			patcher.start()
			self.addCleanup(patcher.stop)

	def test_default_quantity_uom_and_empty_batch(self):
		result = labels.get_labels('["EFB10", "EFB10"]')
		self.assertEqual(len(result), 1)
		self.assertEqual(result[0]["payload"], "EFB10;500;Nos;")
		self.item.check_permission.assert_has_calls([call("read"), call("print")])

	def test_permission_denial_stops_generation(self):
		self.item.check_permission.side_effect = PermissionError
		with self.assertRaises(PermissionError):
			labels.get_labels(["EFB10"])
		labels.generate_qr.assert_not_called()

	def test_invalid_quantity_never_prints(self):
		for qty in (None, 0, -1, float("nan"), float("inf")):
			with self.subTest(qty=qty):
				self.item.get.return_value = qty
				with self.assertRaises(ValueError):
					labels.get_labels(["EFB10"])
		labels.generate_qr.assert_not_called()

	def test_semicolons_rejected(self):
		self.item.stock_uom = "Nos;Other"
		with self.assertRaises(ValueError):
			labels.get_labels(["EFB10"])

	def test_nonstock_or_disabled_items_rejected(self):
		self.item.disabled = 1
		with self.assertRaises(ValueError):
			labels.get_labels(["EFB10"])

	def test_pack_choice_uses_separate_defaults(self):
		self.item.get.side_effect = lambda field: {"custom_standard_pack_qty": 25, "custom_material_scanner_pack_qty": 500}[field]
		self.assertEqual(labels.get_labels(["EFB10"], "standard")[0]["payload"], "EFB10;25;Nos;")
		self.assertEqual(labels.get_labels(["EFB10"], "big")[0]["payload"], "EFB10;500;Nos;")

	def test_unknown_pack_type_rejected(self):
		with self.assertRaises(ValueError):
			labels.get_labels(["EFB10"], "other")
		labels.generate_qr.assert_not_called()
