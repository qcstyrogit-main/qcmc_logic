from unittest import TestCase
from unittest.mock import MagicMock, patch

import frappe

from qcmc_logic.api.delivery_note import create_sales_invoice_from_draft_dn


class TestDraftDeliveryNoteInvoice(TestCase):
	@patch("qcmc_logic.api.delivery_note.get_mapped_doc")
	@patch("qcmc_logic.api.delivery_note.frappe.get_single_value", return_value=1)
	def test_uses_standard_invoice_mapping_and_initialization(
		self, get_single_value, get_mapped_doc
	):
		delivery_note = frappe._dict(company_address="QCMC Address")
		sales_invoice = MagicMock()
		sales_invoice.company_address = "QCMC Address"

		def map_document(source_doctype, source_name, mapping, postprocess=None):
			self.assertEqual(source_doctype, "Delivery Note")
			self.assertEqual(source_name, "DN-0001")
			self.assertEqual(
				mapping["Delivery Note"]["field_map"]["custom_dr_number"],
				"custom_delivery_number",
			)
			item_map = mapping["Delivery Note Item"]["field_map"]
			self.assertEqual(item_map["parent"], "delivery_note")
			self.assertEqual(item_map["against_sales_order"], "sales_order")
			self.assertIn("Sales Taxes and Charges", mapping)
			self.assertIn("Sales Team", mapping)

			postprocess(delivery_note, sales_invoice)
			return sales_invoice

		get_mapped_doc.side_effect = map_document

		result = create_sales_invoice_from_draft_dn("DN-0001")

		self.assertIs(result, sales_invoice)
		run_methods = [call.args[0] for call in sales_invoice.run_method.call_args_list]
		self.assertEqual(
			run_methods,
			[
				"set_missing_values",
				"set_po_nos",
				"calculate_taxes_and_totals",
				"set_use_serial_batch_fields",
			],
		)
		sales_invoice.set_payment_schedule.assert_called_once_with()

	@patch("qcmc_logic.api.delivery_note.get_mapped_doc")
	@patch("qcmc_logic.api.delivery_note.frappe.get_single_value", return_value=0)
	@patch("qcmc_logic.api.delivery_note.frappe.db.get_value", return_value="Net 30")
	@patch("qcmc_logic.api.delivery_note.get_due_date", return_value="2026-10-09")
	def test_inherits_sales_order_payment_terms_when_automatic_fetch_is_disabled(
		self, get_due_date, get_value, get_single_value, get_mapped_doc
	):
		sales_invoice = MagicMock()
		sales_invoice.company_address = None
		sales_invoice.posting_date = "2026-09-09"
		sales_invoice.customer = "CUST-0001"
		sales_invoice.company = "QCMC"
		sales_invoice.get_order_details.return_value = (
			"SO-0001",
			"Sales Order",
			"sales_order",
		)
		sales_invoice.linked_order_has_payment_terms.return_value = True
		get_mapped_doc.return_value = sales_invoice

		create_sales_invoice_from_draft_dn("DN-0001")

		get_value.assert_called_once_with("Sales Order", "SO-0001", "payment_terms_template")
		self.assertEqual(sales_invoice.payment_terms_template, "Net 30")
		get_due_date.assert_called_once_with(
			"2026-09-09",
			"Customer",
			"CUST-0001",
			"QCMC",
			template_name="Net 30",
		)
		self.assertEqual(sales_invoice.due_date, "2026-10-09")
		sales_invoice.set_payment_schedule.assert_not_called()
