"""WTS Checker variance and extra-item validation (no stock ledger writes)."""
import unittest
from unittest.mock import patch, Mock

import frappe

from qcmc_logic.api.warehouse_workflow import WorkflowError
from qcmc_logic.api.warehouse_transfer_scanner import (
    _check_date, _validated_extra_items, _verified_counts,
    _save_checked_receipt, _same_check_request,
)


class TestWtsCheckerVariance(unittest.TestCase):
    def setUp(self):
        self.doc = frappe._dict(transfer_items=[
            frappe._dict(name="WTS-ROW-1", item_code="EXISTING", issued_qty=100),
            frappe._dict(name="WTS-ROW-2", item_code="ANOTHER", issued_qty=20),
        ])

    def test_allows_shortage_excess_and_zero_without_rewriting_issued(self):
        for counts in ((80, 25), (0, 20), (100, 20)):
            with self.subTest(counts=counts):
                result = _verified_counts(self.doc, [
                    {"row_id": "WTS-ROW-1", "checked_quantity": counts[0]},
                    {"row_id": "WTS-ROW-2", "checked_quantity": counts[1]},
                ])
                self.assertEqual(result["WTS-ROW-1"], str(counts[0]))
                self.assertEqual(result["WTS-ROW-2"], str(counts[1]))
                self.assertEqual(self.doc.transfer_items[0].issued_qty, 100)

    def test_checker_writes_received_qty_and_extra_rows_without_changing_issued(self):
        original = frappe._dict(name="WTS-ROW-1", item_code="EXISTING",
                                issued_qty=100, received_qty=0)
        rows = [original]
        doc = frappe._dict(name="WTS-TEST", transfer_items=rows, flags=frappe._dict())
        doc.get = lambda field: rows if field == "transfer_items" else None
        doc.append = lambda field, value: rows.append(frappe._dict(value))
        doc.save = Mock()
        counts = {"WTS-ROW-1": "80"}
        extra = [{"item_code": "EXTRA", "item_name": "Extra",
                  "stock_uom": "PCS", "checked_quantity": "6"}]
        with patch("qcmc_logic.api.warehouse_transfer_scanner.frappe.get_doc", return_value=doc):
            result = _save_checked_receipt(doc, counts, extra)
        self.assertIs(result, doc)
        self.assertEqual(original.issued_qty, 100)
        self.assertEqual(original.received_qty, 80)
        self.assertEqual(rows[1].issued_qty, 0)
        self.assertEqual(rows[1].received_qty, 6)
        self.assertEqual(rows[1].item_code, "EXTRA")
        self.assertTrue(doc.flags.qcmc_wts_checker_sync)
        doc.save.assert_called_once_with(ignore_permissions=True)

    def test_confirm_checker_idempotency_does_not_append_extra_twice(self):
        handover = frappe._dict(
            verified_quantities_json='{"WTS-ROW-1": "80"}',
            extra_items_json='[{"item_code":"EXTRA","checked_quantity":"6"}]',
            check_date="2026-11-12",
        )
        self.assertTrue(_same_check_request(
            handover, [{"row_id": "WTS-ROW-1", "checked_quantity": 80}],
            [{"item_code": "EXTRA", "checked_quantity": 6}], "2026-11-12",
        ))
        self.assertFalse(_same_check_request(
            handover, [{"row_id": "WTS-ROW-1", "checked_quantity": 81}],
            [{"item_code": "EXTRA", "checked_quantity": 6}], "2026-11-12",
        ))

    def test_rejects_missing_duplicate_and_negative_counts(self):
        examples = (
            [{"row_id": "WTS-ROW-1", "checked_quantity": 8}],
            [
                {"row_id": "WTS-ROW-1", "checked_quantity": 8},
                {"row_id": "WTS-ROW-1", "checked_quantity": 8},
            ],
            [
                {"row_id": "WTS-ROW-1", "checked_quantity": -1},
                {"row_id": "WTS-ROW-2", "checked_quantity": 20},
            ],
        )
        for entries in examples:
            with self.subTest(entries=entries), self.assertRaises(WorkflowError):
                _verified_counts(self.doc, entries)

    def test_validates_extra_item_against_item_master(self):
        item = frappe._dict(name="EXTRA", item_name="Other Delivered Item",
                            stock_uom="PCS", disabled=0, is_stock_item=1)
        with patch("qcmc_logic.api.warehouse_transfer_scanner.frappe.db.get_value", return_value=item):
            result = _validated_extra_items(self.doc, [
                {"item_code": "EXTRA", "checked_quantity": 4}
            ])
            self.assertEqual(result[0]["item_code"], "EXTRA")
            self.assertEqual(result[0]["checked_quantity"], "4")

    def test_rejects_extra_item_already_on_wts(self):
        with self.assertRaises(WorkflowError):
            _validated_extra_items(self.doc, [{"item_code": "EXISTING", "checked_quantity": 1}])

    def test_rejects_non_stock_or_disabled_extra_items(self):
        for disabled, stock in ((1, 1), (0, 0)):
            item = frappe._dict(name="EXTRA", item_name="Extra", stock_uom="PCS",
                                disabled=disabled, is_stock_item=stock)
            with patch("qcmc_logic.api.warehouse_transfer_scanner.frappe.db.get_value", return_value=item):
                with self.assertRaises(WorkflowError):
                    _validated_extra_items(self.doc, [{"item_code": "EXTRA", "checked_quantity": 1}])

    def test_accepts_confirmed_iso_date(self):
        self.assertEqual(_check_date("2026-11-11"), "2026-11-11")

    def test_rejects_future_or_invalid_check_date(self):
        for date in ("2099-01-01", "invalid", "2026-02-30", ""):
            with self.subTest(date=date), self.assertRaises(WorkflowError):
                _check_date(date)
