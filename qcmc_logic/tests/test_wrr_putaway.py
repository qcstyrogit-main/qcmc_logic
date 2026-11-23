import json
import unittest
from unittest.mock import patch

import frappe

from qcmc_logic.overrides import putaway_rule_dimension as putaway


class TestWRRPutaway(unittest.TestCase):
    def item(self):
        return dict(doctype="Purchase Receipt Item", name="ROW", idx=1,
                    item_code="ITEM", warehouse="WH", uom="PCS", stock_uom="PCS",
                    qty=5, received_qty=5, stock_qty=5, conversion_factor=1, location="")

    def apply(self, items, sync):
        rules = [
            frappe._dict(name="RULE-A", item_code="ITEM", warehouse="WH", location="LOC-A", free_space=3, priority=1),
            frappe._dict(name="RULE-B", item_code="ITEM", warehouse="WH", location="LOC-B", free_space=10, priority=2),
        ]
        with (
            patch.object(putaway, "get_ordered_dimension_putaway_rules", return_value=(False, rules)),
            patch.object(putaway, "get_dimension_fields_for_doctype", return_value=["location"]),
            patch.object(frappe.db, "get_value", return_value=0),
            patch.object(frappe, "msgprint"),
        ):
            return putaway.apply_dimension_putaway_rule("Purchase Receipt", items, "COMPANY", sync=sync)

    def test_native_checkbox_rpc_override_is_whitelisted(self):
        method = frappe.override_whitelisted_method("erpnext.stock.doctype.putaway_rule.putaway_rule.apply_putaway_rule")
        self.assertEqual(method, "qcmc_logic.overrides.putaway_rule_dimension.apply_dimension_putaway_rule")
        frappe.is_whitelisted(frappe.get_attr(method))

    def test_browser_json_rows_stay_bulk_until_save(self):
        rows = self.apply(json.dumps([self.item()]), "true")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["qty"], 5)
        self.assertEqual(rows[0]["location"], "")

    def test_json_boolean_sync_is_supported(self):
        rows = self.apply([self.item()], True)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["qty"], 5)

    def test_server_child_documents_stay_bulk(self):
        items = [frappe.get_doc(self.item())]
        self.apply(items, None)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].qty, 5)

    def test_non_receiving_stock_entry_boolean_sync_keeps_rows_unchanged(self):
        items = [dict(doctype="Stock Entry Detail", qty=1, s_warehouse="WH")]
        self.assertIs(putaway.apply_dimension_putaway_rule("Stock Entry", items, "COMPANY", sync=True, purpose="Material Issue"), items)


def run_tests():
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(TestWRRPutaway))
    if not result.wasSuccessful():
        raise AssertionError("WRR putaway tests failed")
    return {"tests_run": result.testsRun, "successful": True}
