"""Unit tests for APV VAT reference-only submit validation."""
from unittest import TestCase
from unittest.mock import Mock, patch
from types import SimpleNamespace
import frappe
from qcmc_logic.customs.apv_vat_validation import validate_purchase_invoice
from qcmc_logic.hooks import doc_events


class TestAPVVATValidation(TestCase):
    """Pure unit tests: no site, database, scheduler or FrappeTestCase lifecycle."""

    def setUp(self):
        throw_patcher = patch("frappe.throw", side_effect=frappe.ValidationError)
        throw_patcher.start()
        self.addCleanup(throw_patcher.stop)
        self.get_value = Mock(side_effect=[
            frappe._dict(company="QC Styropackaging Corporation", root_type="Expense", is_group=0, disabled=0),
            frappe._dict(company="QC Styropackaging Corporation", is_group=0, disabled=0),
        ])
        db_patcher = patch.object(frappe, "db", SimpleNamespace(get_value=self.get_value))
        db_patcher.start()
        self.addCleanup(db_patcher.stop)

    def make_invoice(self, amount=12, is_return=False, account="Expense - Q", center="GEN - Q"):
        return frappe._dict(
            company="QC Styropackaging Corporation", is_return=is_return,
            items=[frappe._dict(expense_account=account)],
            custom_vat_details=[frappe._dict(account_name=account, cost_center=center, amount=amount)],
        )

    def test_purchase_invoice_before_submit_hook_registered(self):
        self.assertEqual(
            doc_events["Purchase Invoice"]["before_submit"],
            "qcmc_logic.customs.apv_vat_validation.validate_purchase_invoice",
        )

    def test_vat_details_do_not_mutate_invoice_totals(self):
        invoice = self.make_invoice()
        invoice.grand_total = 112.0
        invoice.total_taxes_and_charges = 12.0
        invoice.base_grand_total = 112.0
        invoice.gl_entries = [frappe._dict(account="Creditors - Q", debit=0, credit=112)]
        before = frappe._dict(
            grand_total=invoice.grand_total,
            total_taxes_and_charges=invoice.total_taxes_and_charges,
            base_grand_total=invoice.base_grand_total,
            gl_entries=[dict(entry) for entry in invoice.gl_entries],
        )
        validate_purchase_invoice(invoice)
        self.assertEqual(invoice.grand_total, before.grand_total)
        self.assertEqual(invoice.total_taxes_and_charges, before.total_taxes_and_charges)
        self.assertEqual(invoice.base_grand_total, before.base_grand_total)
        self.assertEqual([dict(entry) for entry in invoice.gl_entries], before.gl_entries)

    def test_empty_details_allowed(self):
        invoice = self.make_invoice()
        invoice.custom_vat_details = []
        validate_purchase_invoice(invoice)

    def test_zero_amount_rejected(self):
        with self.assertRaises(frappe.ValidationError):
            validate_purchase_invoice(self.make_invoice(amount=0))

    def test_positive_return_rejected(self):
        with self.assertRaises(frappe.ValidationError):
            validate_purchase_invoice(self.make_invoice(amount=12, is_return=True))

    def test_negative_return_allowed(self):
        validate_purchase_invoice(self.make_invoice(amount=-12, is_return=True))

    def test_different_valid_expense_account_allowed(self):
        invoice = self.make_invoice()
        invoice.custom_vat_details[0].account_name = "Other Expense - Q"
        validate_purchase_invoice(invoice)
        self.assertEqual(invoice.custom_vat_details[0].account_name, "Other Expense - Q")

    def test_missing_expense_account_rejected(self):
        invoice = self.make_invoice()
        invoice.custom_vat_details[0].account_name = None
        with self.assertRaises(frappe.ValidationError):
            validate_purchase_invoice(invoice)

    def test_cross_company_cost_center_rejected(self):
        self.get_value.side_effect = [
            frappe._dict(company="QC Styropackaging Corporation", root_type="Expense", is_group=0, disabled=0),
            frappe._dict(company="Multiplast Corporation", is_group=0, disabled=0),
        ]
        with self.assertRaises(frappe.ValidationError):
            validate_purchase_invoice(self.make_invoice())
