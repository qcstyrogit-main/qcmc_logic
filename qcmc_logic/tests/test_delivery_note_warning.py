from unittest import TestCase
from unittest.mock import patch

import frappe

from qcmc_logic.customs.delivery_note_warning import (
    get_sales_order_delivery_warning,
)


class TestDeliveryNoteWarning(TestCase):
    def _delivery_note(self, stock_qty=6, name="DN-NEW"):
        return {
            "doctype": "Delivery Note",
            "name": name,
            "items": [
                {
                    "against_sales_order": "SO-1",
                    "so_detail": "SOI-1",
                    "item_code": "ITEM-1",
                    "stock_qty": stock_qty,
                }
            ],
        }

    def _sales_order_items(self, ordered_qty=10):
        return [
            frappe._dict(
                name="SOI-1",
                parent="SO-1",
                item_code="ITEM-1",
                stock_qty=ordered_qty,
            )
        ]

    def test_existing_draft_delivery_note_warns(self):
        existing = [
            frappe._dict(
                so_detail="SOI-1",
                delivery_note="DN-DRAFT",
                docstatus=0,
                delivered_stock_qty=2,
            )
        ]
        with (
            patch(
                "qcmc_logic.customs.delivery_note_warning.frappe.has_permission",
                return_value=True,
            ),
            patch(
                "qcmc_logic.customs.delivery_note_warning.frappe.get_all",
                return_value=self._sales_order_items(),
            ),
            patch(
                "qcmc_logic.customs.delivery_note_warning.frappe.db.sql",
                return_value=existing,
            ),
        ):
            result = get_sales_order_delivery_warning(self._delivery_note())

        self.assertTrue(result["has_warning"])
        self.assertIn("DN-DRAFT", result["message"])
        self.assertIn("Draft", result["message"])

    def test_combined_delivery_quantity_over_order_warns(self):
        existing = [
            frappe._dict(
                so_detail="SOI-1",
                delivery_note="DN-1",
                docstatus=1,
                delivered_stock_qty=5,
            )
        ]
        with (
            patch(
                "qcmc_logic.customs.delivery_note_warning.frappe.has_permission",
                return_value=True,
            ),
            patch(
                "qcmc_logic.customs.delivery_note_warning.frappe.get_all",
                return_value=self._sales_order_items(),
            ),
            patch(
                "qcmc_logic.customs.delivery_note_warning.frappe.db.sql",
                return_value=existing,
            ),
        ):
            result = get_sales_order_delivery_warning(self._delivery_note(stock_qty=6))

        self.assertTrue(result["has_warning"])
        self.assertIn("Exceeds ordered quantity", result["message"])

    def test_no_existing_delivery_and_within_quantity_does_not_warn(self):
        with (
            patch(
                "qcmc_logic.customs.delivery_note_warning.frappe.has_permission",
                return_value=True,
            ),
            patch(
                "qcmc_logic.customs.delivery_note_warning.frappe.get_all",
                return_value=self._sales_order_items(),
            ),
            patch(
                "qcmc_logic.customs.delivery_note_warning.frappe.db.sql",
                return_value=[],
            ),
        ):
            result = get_sales_order_delivery_warning(self._delivery_note(stock_qty=6))

        self.assertFalse(result["has_warning"])

