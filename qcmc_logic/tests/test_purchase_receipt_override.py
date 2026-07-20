from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from qcmc_logic.overrides.purchase_receipt import make_purchase_invoice


class TestPurchaseReceiptOverride(TestCase):
	@patch("qcmc_logic.overrides.purchase_receipt.frappe")
	@patch("qcmc_logic.overrides.purchase_receipt._make_erpnext_purchase_invoice")
	def test_maps_supplier_invoice_details(self, make_invoice, frappe_mock):
		purchase_invoice = SimpleNamespace(bill_no=None, bill_date=None)
		make_invoice.return_value = purchase_invoice
		frappe_mock.db.get_value.return_value = ("SUP-INV-001", "2026-07-17")

		result = make_purchase_invoice("PREC-0001")

		make_invoice.assert_called_once_with("PREC-0001", None, None)
		frappe_mock.db.get_value.assert_called_once_with(
			"Purchase Receipt",
			"PREC-0001",
			["custom_invoice_number", "posting_date"],
		)
		self.assertEqual(result.bill_no, "SUP-INV-001")
		self.assertEqual(result.bill_date, "2026-07-17")
