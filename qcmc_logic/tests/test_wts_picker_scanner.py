"""Unit guards for WTS physical allocation, with no stock-ledger writes."""
import unittest
from unittest.mock import patch

import frappe

from qcmc_logic.api.warehouse_workflow import WorkflowError
from qcmc_logic.api.wts_picker_scanner import validate_scanner_allocations


class TestWtsPickerScanner(unittest.TestCase):
    def setUp(self):
        self.item = frappe._dict(
            name="WTS-ITEM-1", item_code="ITEM-001", issued_qty=10,
            received_qty=10,
        )
        self.transfer = frappe._dict(
            name="WTS-TEST-1", target_warehouse="Target Warehouse",
            custom_storage_allocation_enabled=1, transfer_items=[self.item],
        )
        self.row = frappe._dict(
            source_doctype="Warehouse Transfer", source_document="WTS-TEST-1",
            source_row="WTS-ITEM-1", item_code="ITEM-001", stock_uom="PCS",
            suggested_qty=10, actual_qty=10, actual_location="LOC-1",
            status="VERIFIED",
        )
        self.allocation = frappe._dict(
            name="WA-TEST-1", status="In Progress", warehouse="Target Warehouse",
            docstatus=0, locations=[self.row],
        )
        self.location = frappe._dict(
            name="LOC-1", disabled=0, is_group=0,
            custom_warehouse="Target Warehouse", custom_restricted_item="",
        )

    def _validate(self):
        with (
            patch("qcmc_logic.api.wts_picker_scanner.linked_allocations", return_value=[self.allocation]),
            patch("qcmc_logic.api.wts_picker_scanner.stock_quantity", side_effect=lambda item, quantity: (quantity, frappe._dict(is_stock_item=1, stock_uom="PCS"))),
            patch("qcmc_logic.api.wts_picker_scanner.frappe.get_cached_doc", return_value=self.location),
        ):
            return validate_scanner_allocations(self.transfer)

    def test_checker_received_qty_controls_physical_allocation_not_issued_qty(self):
        # When Checker receives 8 from 10 issued, allocation must track 8.
        self.item.received_qty = 8
        self.row.suggested_qty = 8
        self.row.actual_qty = 8
        self.assertEqual(self._validate(), [self.allocation])
        self.assertEqual(self.item.issued_qty, 10)

    def test_zero_received_row_needs_no_location_if_another_row_received(self):
        missing = frappe._dict(name="WTS-ITEM-2", item_code="ITEM-002",
                               issued_qty=7, received_qty=0)
        self.transfer.transfer_items.append(missing)
        self.assertEqual(self._validate(), [self.allocation])

    def test_extra_receiver_row_uses_zero_issued_qty_and_received_qty(self):
        extra = frappe._dict(name="WTS-ITEM-EXTRA", item_code="ITEM-EXTRA",
                             issued_qty=0, received_qty=6)
        self.transfer.transfer_items.append(extra)
        extra_allocation = frappe._dict(
            source_doctype="Warehouse Transfer", source_document="WTS-TEST-1",
            source_row="WTS-ITEM-EXTRA", item_code="ITEM-EXTRA", stock_uom="PCS",
            suggested_qty=6, actual_qty=6, actual_location="LOC-1",
            status="VERIFIED",
        )
        self.allocation.locations.append(extra_allocation)
        self.assertEqual(self._validate(), [self.allocation])

    def test_complete_physical_verification_preserves_actual_location(self):
        self.assertEqual(self._validate(), [self.allocation])
        self.assertEqual(self.row.actual_location, "LOC-1")

    def test_unverified_location_cannot_be_received(self):
        self.row.status = "PENDING_VERIFICATION"
        with self.assertRaises(WorkflowError):
            self._validate()

    def test_mismatched_quantity_cannot_be_received(self):
        self.row.actual_qty = 9
        with self.assertRaises(WorkflowError):
            self._validate()

    def test_unexpected_source_row_cannot_be_received(self):
        self.row.source_row = "OTHER-ITEM"
        with self.assertRaises(WorkflowError):
            self._validate()

    def test_wrong_warehouse_location_cannot_be_received(self):
        self.location.custom_warehouse = "Other Warehouse"
        with self.assertRaises(WorkflowError):
            self._validate()
