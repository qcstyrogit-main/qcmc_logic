"""Isolated printing checks; no site connection or database writes."""
from copy import deepcopy
import sys
from unittest import TestCase
from unittest.mock import MagicMock, patch

import frappe

from qcmc_logic.qcmc_logics.report.delivery_note_printing import delivery_note_printing as printing


class TestPrintingPreview(TestCase):
	def setUp(self):
		self.dn = MagicMock(name="Delivery Note")
		self.dn.name = "DN-test"
		self.dn.get.side_effect = {"custom_dr_number": "DR-test"}.get
		self.dn.items = [frappe._dict(name="DNI-test", item_code="A", qty=100, uom="Nos", conversion_factor=1)]
		self.invoice = MagicMock()
		self.invoice.name = "SI-test"
		self.invoice.docstatus = 0
		self.invoice.custom_invoice_number = "INV-test"
		self.invoice.custom_delivery_number = "DR-test"
		self.invoice.get.side_effect = lambda key: getattr(self.invoice, key)
		self.invoice.items = [frappe._dict(dn_detail="DNI-test", delivery_note="DN-test", item_code="A", qty=100, uom="Nos", conversion_factor=1)]
		for patcher in (
			patch.object(printing, "_validate_invoicing_role"),
			patch.object(printing, "_", side_effect=lambda value: value),
			patch.object(printing.frappe, "get_doc", side_effect=lambda doctype, name: self.dn if doctype == "Delivery Note" else self.invoice),
			patch.object(printing.frappe, "throw", side_effect=ValueError),
		):
			patcher.start()
			self.addCleanup(patcher.stop)

	def verify(self):
		return printing.verify_sales_invoice_for_preview("DN-test", "INV-test", "SI-test")

	def test_matching_invoice_passes(self):
		self.assertTrue(self.verify()["verified"])
		self.invoice.check_permission.assert_any_call("read")
		self.invoice.check_permission.assert_any_call("print")

	def test_mismatched_quantity_fails(self):
		self.invoice.items[0].qty = 1
		with self.assertRaises(ValueError):
			self.verify()

	def test_extra_or_duplicate_item_fails(self):
		for detail in ("DNI-test", "unrelated"):
			with self.subTest(detail=detail):
				self.invoice.items = self.invoice.items[:1] + [deepcopy(self.invoice.items[0])]
				self.invoice.items[1].dn_detail = detail
				with self.assertRaises(ValueError):
					self.verify()

	def test_missing_item_fails(self):
		self.invoice.items = []
		with self.assertRaises(ValueError):
			self.verify()

	def test_wrong_delivery_note_fails(self):
		self.invoice.items[0].delivery_note = "Other-DN"
		with self.assertRaises(ValueError):
			self.verify()

	def test_submitted_invoice_fails(self):
		self.invoice.docstatus = 1
		with self.assertRaises(ValueError):
			self.verify()

	def test_preview_by_name_uses_saved_number(self):
		self.assertTrue(printing.verify_sales_invoice_for_preview("DN-test", sales_invoice="SI-test")["verified"])

	def test_default_print_format(self):
		with patch.object(printing.frappe, "get_meta", return_value=frappe._dict(default_print_format="Configured Default")):
			self.assertEqual(printing._get_print_format("QC Styropackaging Corporation"), "Configured Default")

	def test_creation_retry_verifies_existing_invoice(self):
		mapper = MagicMock()
		with (
			patch.object(printing.frappe, "db", MagicMock(get_value=MagicMock(return_value="SI-test"))),
			patch.object(printing.frappe, "cache", MagicMock()),
			patch.object(printing.frappe, "has_permission", return_value=True),
			patch.object(printing.frappe, "get_meta", return_value=MagicMock(get_field=MagicMock(return_value=frappe._dict(length=10)))),
			patch.dict(sys.modules, {"qcmc_logic.api.delivery_note": MagicMock(create_sales_invoice_from_draft_dn=mapper)}),
		):
			result = printing.create_sales_invoices('["DN-test"]', "INV-test")
			self.assertTrue(result["verified"])
			mapper.assert_not_called()
