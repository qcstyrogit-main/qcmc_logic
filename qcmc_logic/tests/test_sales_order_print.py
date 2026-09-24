from unittest import TestCase

import frappe

from qcmc_logic.customs.sales_order_print import get_sales_order_slip_items


class TestSalesOrderPrint(TestCase):
    def test_sales_order_slip_helper_is_available_to_jinja(self):
        methods = frappe.get_hooks("jinja").get("methods") or []

        self.assertIn(
            "qcmc_logic.customs.sales_order_print.get_sales_order_slip_items",
            methods,
        )

    def test_sales_order_slip_items_add_summary_rows_after_staggered_deliveries(self):
        doc = frappe._dict(
            items=[
                frappe._dict(
                    item_code="ITEM-1",
                    item_name="EPS Board",
                    uom="PCS",
                    qty=10,
                    rate=25,
                    amount=250,
                    delivery_date="2026-10-01",
                ),
                frappe._dict(
                    item_code="ITEM-1",
                    item_name="EPS Board",
                    uom="PCS",
                    qty=15,
                    rate=25,
                    amount=375,
                    delivery_date="2026-10-08",
                ),
                frappe._dict(
                    item_code="ITEM-2",
                    item_name="Tape",
                    uom="ROLL",
                    qty=3,
                    rate=40,
                    amount=120,
                    delivery_date="2026-10-01",
                ),
            ]
        )

        rows = get_sales_order_slip_items(doc)

        self.assertEqual(len(rows), 5)
        self.assertEqual(rows[0].item_code, "ITEM-1")
        self.assertEqual(rows[0].qty, 10)
        self.assertEqual(rows[0].delivery_date, "2026-10-01")
        self.assertFalse(rows[0].is_summary)
        self.assertEqual(rows[1].item_code, "ITEM-1")
        self.assertEqual(rows[1].qty, 15)
        self.assertEqual(rows[1].delivery_date, "2026-10-08")
        self.assertFalse(rows[1].is_summary)
        self.assertEqual(rows[2].item_code, "ITEM-1")
        self.assertEqual(rows[2].qty, 25)
        self.assertEqual(rows[2].amount, 625)
        self.assertEqual(rows[2].delivery_date, "")
        self.assertTrue(rows[2].is_summary)
        self.assertEqual(rows[3].item_code, "ITEM-2")
        self.assertEqual(rows[4].item_code, "ITEM-2")
        self.assertTrue(rows[4].is_summary)

    def test_sales_order_slip_items_keeps_different_rates_separate(self):
        doc = frappe._dict(
            items=[
                frappe._dict(item_code="ITEM-1", item_name="EPS Board", uom="PCS", qty=10, rate=25, amount=250),
                frappe._dict(item_code="ITEM-1", item_name="EPS Board", uom="PCS", qty=10, rate=30, amount=300),
            ]
        )

        rows = get_sales_order_slip_items(doc)

        self.assertEqual([row.rate for row in rows], [25, 25, 30, 30])
        self.assertEqual([row.is_summary for row in rows], [0, 1, 0, 1])
