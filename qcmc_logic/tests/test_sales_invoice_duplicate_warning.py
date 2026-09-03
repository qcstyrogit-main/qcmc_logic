from unittest import TestCase
from unittest.mock import patch

from frappe import _dict

from qcmc_logic.overrides.sales_invoice_override import (
    _get_duplicate_invoice_reference_matches,
    _get_item_references,
    _same_currency_and_total,
    warn_duplicate_invoice_references,
)


def invoice_doc(name="ACC-SINV-TEST", is_return=0, currency="PHP", grand_total=100, items=None):
    return _dict(
        name=name,
        is_return=is_return,
        currency=currency,
        grand_total=grand_total,
        items=items or [],
    )


class TestSalesInvoiceDuplicateWarning(TestCase):
    def test_another_draft_invoice_against_same_delivery_note_warns(self):
        doc = invoice_doc(
            items=[_dict(delivery_note="DN-1", dn_detail="DNI-1")],
        )

        with patch("qcmc_logic.overrides.sales_invoice_override.frappe") as frappe:
            frappe.db.sql.return_value = [
                _dict(
                    name="SINV-DRAFT",
                    docstatus=0,
                    currency="PHP",
                    grand_total=50,
                    sales_order=None,
                    delivery_note="DN-1",
                )
            ]
            matches = _get_duplicate_invoice_reference_matches(doc, _get_item_references(doc))

        self.assertEqual(matches[0].name, "SINV-DRAFT")
        self.assertEqual(matches[0].docstatus, 0)
        self.assertEqual(matches[0].delivery_notes, ["DN-1"])

    def test_another_submitted_invoice_against_same_delivery_note_warns(self):
        doc = invoice_doc(
            items=[_dict(delivery_note="DN-1", dn_detail="DNI-1")],
        )

        with patch("qcmc_logic.overrides.sales_invoice_override.frappe") as frappe:
            frappe.db.sql.return_value = [
                _dict(
                    name="SINV-SUBMITTED",
                    docstatus=1,
                    currency="PHP",
                    grand_total=50,
                    sales_order=None,
                    delivery_note="DN-1",
                )
            ]
            matches = _get_duplicate_invoice_reference_matches(doc, _get_item_references(doc))

        self.assertEqual(matches[0].name, "SINV-SUBMITTED")
        self.assertEqual(matches[0].docstatus, 1)

    def test_same_sales_order_with_no_delivery_note_warns(self):
        doc = invoice_doc(
            items=[_dict(sales_order="SO-1", so_detail="SOI-1")],
        )

        with patch("qcmc_logic.overrides.sales_invoice_override.frappe") as frappe:
            frappe.db.sql.return_value = [
                _dict(
                    name="SINV-SO",
                    docstatus=0,
                    currency="PHP",
                    grand_total=25,
                    sales_order="SO-1",
                    delivery_note=None,
                )
            ]
            matches = _get_duplicate_invoice_reference_matches(doc, _get_item_references(doc))

        self.assertEqual(matches[0].sales_orders, ["SO-1"])

    def test_partial_invoices_with_different_item_references_do_not_match(self):
        doc = invoice_doc(
            items=[_dict(sales_order="SO-1", so_detail="SOI-1")],
        )

        with patch("qcmc_logic.overrides.sales_invoice_override.frappe") as frappe:
            frappe.db.sql.return_value = []
            matches = _get_duplicate_invoice_reference_matches(doc, _get_item_references(doc))
            values = frappe.db.sql.call_args.args[1]

        self.assertEqual(matches, [])
        self.assertEqual(values["ref_name_0"], "SO-1")
        self.assertEqual(values["detail_name_0"], "SOI-1")

    def test_cancelled_invoices_are_excluded_by_query(self):
        doc = invoice_doc(
            items=[_dict(delivery_note="DN-1", dn_detail="DNI-1")],
        )

        with patch("qcmc_logic.overrides.sales_invoice_override.frappe") as frappe:
            frappe.db.sql.return_value = []
            _get_duplicate_invoice_reference_matches(doc, _get_item_references(doc))
            query = frappe.db.sql.call_args.args[0]

        self.assertIn("si.docstatus in (0, 1)", query)

    def test_returns_do_not_warn(self):
        doc = invoice_doc(
            is_return=1,
            items=[_dict(delivery_note="DN-1", dn_detail="DNI-1")],
        )

        with patch("qcmc_logic.overrides.sales_invoice_override.frappe") as frappe:
            warn_duplicate_invoice_references(doc)

        frappe.db.sql.assert_not_called()
        frappe.msgprint.assert_not_called()

    def test_editing_same_invoice_does_not_self_warn(self):
        doc = invoice_doc(
            name="SINV-CURRENT",
            items=[_dict(delivery_note="DN-1", dn_detail="DNI-1")],
        )

        with patch("qcmc_logic.overrides.sales_invoice_override.frappe") as frappe:
            frappe.db.sql.return_value = []
            _get_duplicate_invoice_reference_matches(doc, _get_item_references(doc))
            values = frappe.db.sql.call_args.args[1]

        self.assertEqual(values["current_invoice"], "SINV-CURRENT")

    def test_same_total_is_possible_duplicate(self):
        doc = invoice_doc(currency="PHP", grand_total=100)
        match = _dict(currency="PHP", grand_total=100)

        self.assertTrue(_same_currency_and_total(doc, match))
