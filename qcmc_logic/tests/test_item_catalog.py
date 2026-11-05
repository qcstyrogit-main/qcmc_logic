"""Focused contract tests for the scanner-only Item Catalog API."""
from unittest.mock import patch

import frappe
from frappe.tests import UnitTestCase
from qcmc_logic.api.item_catalog import get_items, MAX_PAGE_SIZE


class TestItemCatalog(UnitTestCase):
    def test_rejects_unauthenticated_requests(self):
        with patch("qcmc_logic.api.item_catalog.extract_mobile_token", return_value=""), \
             patch.dict(frappe.session, {"user": "Guest"}):
            with self.assertRaises(frappe.AuthenticationError):
                get_items(limit=5)

    def test_page_has_only_allowlisted_fields_and_stable_cursor(self):
        row1 = frappe._dict(name="ITEM-A", item_name="Blue item", description="Blue",
                           stock_uom="PCS", modified="2026-11-05 10:00:00", disabled=0)
        row2 = frappe._dict(name="ITEM-B", item_name="Red item", description="Red",
                           stock_uom="PCS", modified="2026-11-05 10:00:00", disabled=0)
        with patch("qcmc_logic.api.item_catalog._require_catalog_user", return_value="scanner@example.com"), \
             patch("qcmc_logic.api.item_catalog.now_datetime", return_value="2026-11-05 11:00:00"), \
             patch("qcmc_logic.api.item_catalog._get_fg_group_bounds", return_value=[(10, 50)]), \
             patch.object(frappe.db, "sql", return_value=[row1, row2]) as query:
            response = get_items(limit=1)
        self.assertTrue(response["success"])
        self.assertTrue(response["has_more"])
        self.assertEqual(response["next_cursor_item_code"], "ITEM-A")
        self.assertEqual(len(response["items"]), 1)
        self.assertEqual(set(response["items"][0]), {
            "name", "item_name", "description", "stock_uom", "modified", "disabled"
        })
        self.assertIn("order by item.modified asc, item.name asc", query.call_args.args[0])
        self.assertIn("item_group_record.lft >=", query.call_args.args[0])
        self.assertIn("and ((item_group_record.lft >=", query.call_args.args[0].split("where ", 1)[1])
        self.assertEqual(query.call_args.args[1]["fg_lft_0"], 10)
        self.assertEqual(query.call_args.args[1]["fg_rgt_0"], 50)
        self.assertEqual(query.call_args.args[1]["page_size"], 2)

    def test_incremental_sync_sends_tombstones_for_items_moved_out_of_fg(self):
        non_fg = frappe._dict(name="ITEM-OLD", item_name="", description="",
                             stock_uom="", modified="2026-11-05 10:30:00", disabled=1)
        with patch("qcmc_logic.api.item_catalog._require_catalog_user", return_value="scanner@example.com"), \
             patch("qcmc_logic.api.item_catalog.now_datetime", return_value="2026-11-05 11:00:00"), \
             patch("qcmc_logic.api.item_catalog._get_fg_group_bounds", return_value=[(10, 50)]), \
             patch.object(frappe.db, "sql", return_value=[non_fg]) as query:
            response = get_items(since_modified="2026-11-05 10:00:00", limit=500)
        self.assertEqual(response["items"][0]["disabled"], 1)
        self.assertNotIn(" and (item_group_record.lft >=", query.call_args.args[0].split("where ", 1)[1])
        self.assertEqual(query.call_args.args[1]["since"], "2026-11-05 10:00:00")

    def test_rejects_partial_pagination_cursor(self):
        with patch("qcmc_logic.api.item_catalog._require_catalog_user", return_value="scanner@example.com"):
            with self.assertRaises(frappe.ValidationError):
                get_items(cursor_modified="2026-11-05 10:00:00", limit=10)

    def test_page_size_is_capped(self):
        with patch("qcmc_logic.api.item_catalog._require_catalog_user", return_value="scanner@example.com"):
            with self.assertRaises(frappe.ValidationError):
                get_items(limit=MAX_PAGE_SIZE + 1)
