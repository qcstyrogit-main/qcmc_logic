from unittest import TestCase
from unittest.mock import MagicMock, call, patch

import frappe

from qcmc_logic.api.delivery_note import create_sales_invoice_from_draft_dn
from qcmc_logic.api.delivery_note import apply_sales_order_item_pricing


class TestDraftDeliveryNoteInvoice(TestCase):
	@patch("qcmc_logic.api.delivery_note.frappe.get_doc")
	def test_applies_sales_order_item_pricing_without_changing_invoice_qty(self, get_doc):
		get_doc.return_value = frappe._dict(
			rate=0.506,
			base_rate=31.6068,
			price_list_rate=0.506,
			base_price_list_rate=31.6068,
			discount_percentage=0,
			discount_amount=0,
			margin_type="",
			margin_rate_or_amount=0,
			amount=101200,
		)
		source = frappe._dict(name="ilo9abimco", so_detail="dhveaq11tc", qty=1800)
		target = frappe._dict(qty=1800, rate=0, amount=0)

		apply_sales_order_item_pricing(source, target)

		get_doc.assert_called_once_with("Sales Order Item", "dhveaq11tc")
		self.assertEqual(target.qty, 1800)
		self.assertEqual(target.rate, 0.506)
		self.assertEqual(target.base_rate, 31.6068)
		self.assertEqual(target.price_list_rate, 0.506)
		self.assertEqual(target.base_price_list_rate, 31.6068)
		self.assertEqual(target.amount, 0)

	@patch("qcmc_logic.api.delivery_note.frappe.get_doc")
	def test_skips_sales_order_pricing_when_delivery_note_item_has_no_so_detail(self, get_doc):
		source = frappe._dict(name="DNI-0001", so_detail=None, qty=3)
		target = frappe._dict(qty=3, rate=99)

		apply_sales_order_item_pricing(source, target)

		get_doc.assert_not_called()
		self.assertEqual(target.rate, 99)

	@patch("qcmc_logic.api.delivery_note.get_mapped_doc")
	@patch("qcmc_logic.api.delivery_note.frappe.get_doc")
	@patch("qcmc_logic.api.delivery_note.frappe.get_single_value", return_value=1)
	def test_uses_standard_invoice_mapping_and_initialization(
		self, get_single_value, get_doc, get_mapped_doc
	):
		delivery_note = frappe._dict(company_address="QCMC Address")
		sales_invoice = MagicMock()
		sales_invoice.company_address = "QCMC Address"
		source_item = frappe._dict(name="DNI-0001", so_detail="SOI-0001", qty=1800)
		target_item = frappe._dict(qty=0, rate=0)
		get_doc.return_value = frappe._dict(
			rate=0.506,
			base_rate=31.6068,
			price_list_rate=0.506,
			base_price_list_rate=31.6068,
			discount_percentage=0,
			discount_amount=0,
			margin_type="",
			margin_rate_or_amount=0,
		)

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

			mapping["Delivery Note Item"]["postprocess"](
				source_item, target_item, delivery_note
			)
			postprocess(delivery_note, sales_invoice)
			return sales_invoice

		get_mapped_doc.side_effect = map_document

		result = create_sales_invoice_from_draft_dn("DN-0001")

		self.assertIs(result, sales_invoice)
		self.assertIn(call("Sales Order Item", "SOI-0001"), get_doc.call_args_list)
		self.assertEqual(target_item.qty, 1800)
		self.assertEqual(target_item.rate, 0.506)
		self.assertEqual(target_item.base_rate, 31.6068)
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
