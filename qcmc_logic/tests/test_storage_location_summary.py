import unittest
from unittest.mock import patch

import frappe


def module():
    from qcmc_logic.qcmc_logics.report.storage_location_summary import storage_location_summary
    return storage_location_summary


class TestStorageLocationSummary(unittest.TestCase):
    def locations(self):
        return [
            dict(name="BUILDING", location_name="Building", location_type="Building", parent_storage_location="", custom_warehouse="WH", is_group=1),
            dict(name="RACK-10", location_name="Rack 10", location_type="Rack", parent_storage_location="BUILDING", custom_warehouse="WH", is_group=0),
            dict(name="RACK-2", location_name="Rack 2", location_type="Rack", parent_storage_location="BUILDING", custom_warehouse="WH", is_group=0),
            dict(name="EMPTY", location_name="Empty", location_type="Bin", parent_storage_location="BUILDING", custom_warehouse="WH", is_group=0),
            dict(name="FOREIGN", location_name="Other warehouse", location_type="Building", parent_storage_location="", custom_warehouse="OTHER", is_group=0),
        ]

    def balances(self):
        return [
            dict(item_code="ITEM-A", item_name="Alpha", location="RACK-2", warehouse="WH", stock_uom="PCS", quantity=7),
            dict(item_code="ITEM-A", item_name="Alpha", location="RACK-10", warehouse="WH", stock_uom="PCS", quantity=3),
            dict(item_code="ITEM-B", item_name="Beta", location="RACK-10", warehouse="WH", stock_uom="PCS", quantity=5),
            dict(item_code="ZERO", location="EMPTY", warehouse="WH", stock_uom="PCS", quantity=0),
            dict(item_code="FOREIGN", location="FOREIGN", warehouse="OTHER", stock_uom="PCS", quantity=999),
        ]

    def rows(self, **filters):
        return module().build_tree(self.locations(), self.balances(), dict(warehouse="WH", **filters))

    def test_tree_rolls_up_stock_once_and_counts_distinct_items(self):
        rows = self.rows()
        root = rows[0]
        self.assertEqual((root["entry"], root["stock_qty"], root["item_count"]), ("BUILDING", 15, 2))
        self.assertEqual([row["entry"] for row in rows if row["entry_type"] == "Storage Location"], ["BUILDING", "RACK-2", "RACK-10"])
        rack = next(row for row in rows if row["entry"] == "RACK-2")
        item = next(row for row in rows if row["entry"] == "ITEM-A")
        self.assertEqual(item["indent"], rack["indent"] + 1)
        self.assertEqual(item["parent_node"], rack["node_id"])
        self.assertEqual(len({row["node_id"] for row in rows}), len(rows))
        self.assertFalse(any(row["entry"] in {"FOREIGN", "ZERO", "EMPTY"} for row in rows))

    def test_branch_filter_includes_descendants_and_resets_indent(self):
        rows = self.rows(storage_location="RACK-10")
        self.assertEqual([row["entry"] for row in rows], ["RACK-10", "ITEM-A", "ITEM-B"])
        self.assertEqual(rows[0]["indent"], 0)
        self.assertEqual(rows[0]["stock_qty"], 8)

    def test_item_filter_recalculates_parent_totals(self):
        rows = self.rows(item_code="ITEM-B")
        self.assertEqual([row["entry"] for row in rows], ["BUILDING", "RACK-10", "ITEM-B"])
        self.assertEqual((rows[0]["stock_qty"], rows[0]["item_count"]), (5, 1))

    def test_show_empty_keeps_empty_locations_without_zero_stock_items(self):
        rows = self.rows(show_empty_locations=1)
        empty = next(row for row in rows if row["entry"] == "EMPTY")
        self.assertEqual((empty["stock_qty"], empty["item_count"]), (0, 0))
        self.assertFalse(any(row["entry"] == "ZERO" for row in rows))

    def test_mixed_units_are_separate_in_parent_summary(self):
        balances = self.balances()
        balances[2]["stock_uom"] = "KG"
        rows = module().build_tree(self.locations(), balances, dict(warehouse="WH"))
        self.assertIsNone(rows[0]["stock_qty"])
        self.assertEqual(rows[0]["stock_uom"], "Mixed")
        self.assertIn("5 KG", rows[0]["quantity_by_uom"])
        self.assertIn("10 PCS", rows[0]["quantity_by_uom"])

    def test_filtered_out_locations_never_contribute_to_totals(self):
        locations = [row for row in self.locations() if row["name"] != "RACK-10"]
        rows = module().build_tree(locations, self.balances(), dict(warehouse="WH"))
        self.assertEqual(rows[0]["stock_qty"], 7)
        self.assertEqual(rows[0]["item_count"], 1)

    def test_execute_rejects_warehouse_before_reading_balances(self):
        report = module()
        with (
            patch.object(frappe, "has_permission", return_value=True),
            patch.object(report, "check_warehouse_access", return_value=False),
            patch.object(report, "get_balances") as read,
        ):
            with self.assertRaises(frappe.PermissionError):
                report.execute(dict(warehouse="FORBIDDEN"))
            read.assert_not_called()

    def test_execute_applies_item_permissions_before_parent_totals(self):
        report = module()
        # Load real schema before mocking get_list for permission-filtered rows.
        frappe.get_meta("Storage Location")
        with (
            patch.object(frappe, "has_permission", return_value=True),
            patch.object(report, "check_warehouse_access", return_value=True),
            patch.object(report, "get_balances", return_value=self.balances()),
            patch.object(report, "get_capacity_rules", return_value=[]),
            patch.object(frappe, "get_list", side_effect=lambda doctype, **kwargs: self.locations() if doctype == "Storage Location" else ["ITEM-B"]),
        ):
            columns, rows, message = report.execute(dict(warehouse="WH"))
        self.assertEqual((rows[0]["stock_qty"], rows[0]["item_count"]), (5, 1))
        self.assertFalse(any(row["entry"] == "ITEM-A" for row in rows))

    def capacity_rows(self, **filters):
        locations = self.locations()
        for row in locations:
            row["custom_storage_capacity"] = {"RACK-2": 10, "RACK-10": 20, "EMPTY": 5}.get(row["name"], 0)
        return module().build_tree(locations, self.balances(), dict(warehouse="WH", **filters))

    def test_capacity_is_blank_on_parent_and_preserved_on_leaf_locations(self):
        rows = self.capacity_rows()
        root = rows[0]
        for field in ("capacity", "used_capacity", "available_capacity", "use_percentage"):
            self.assertIsNone(root[field])
        self.assertEqual(root["capacity_uom"], "")
        self.assertFalse(root["capacity_unlimited"])
        rack = next(row for row in rows if row["entry"] == "RACK-2")
        self.assertEqual((rack["capacity"], rack["used_capacity"], rack["available_capacity"], rack["use_percentage"]), (10, 7, 3, 70))
        self.assertTrue(all(row["capacity"] is None for row in rows if row["entry_type"] == "Item"))

    def test_item_filter_does_not_make_occupied_capacity_available(self):
        rows = self.capacity_rows(item_code="ITEM-B")
        rack = next(row for row in rows if row["entry"] == "RACK-10")
        self.assertEqual(rack["stock_qty"], 5)
        self.assertEqual((rack["used_capacity"], rack["available_capacity"]), (8, 12))
        self.assertIsNone(rows[0]["used_capacity"])

    def test_parent_with_explicit_unlimited_rule_still_has_blank_capacity(self):
        rules = [dict(name="UNLIMITED", location="BUILDING", custom_no_capacity_restriction=1)]
        rows = module().build_tree(self.locations(), self.balances(), dict(warehouse="WH"), capacity_rules=rules)
        self.assertIsNone(rows[0]["capacity"])
        self.assertFalse(rows[0]["capacity_unlimited"])

    def test_putaway_capacity_overrides_location_field_and_overfill_is_visible(self):
        rules = [dict(name="RULE", location="RACK-2", stock_capacity=5, stock_uom="PCS")]
        rows = module().build_tree(self.locations(), self.balances(), dict(warehouse="WH"), capacity_rules=rules)
        rack = next(row for row in rows if row["entry"] == "RACK-2")
        self.assertEqual((rack["capacity"], rack["available_capacity"], rack["use_percentage"]), (5, 0, 140))

    def test_unlimited_capacity_has_no_false_zero_or_percentage(self):
        rules = [dict(name="UNLIMITED", location="RACK-2", custom_no_capacity_restriction=1)]
        rows = module().build_tree(self.locations(), self.balances(), dict(warehouse="WH"), capacity_rules=rules)
        rack = next(row for row in rows if row["entry"] == "RACK-2")
        self.assertTrue(rack["capacity_unlimited"])
        self.assertEqual(rack["used_capacity"], 7)
        self.assertIsNone(rack["capacity"])
        self.assertIsNone(rack["available_capacity"])
        self.assertIsNone(rack["use_percentage"])

    def test_capacity_columns_survive_rate_guard(self):
        from rate_guard.overrides import _remove_financial_columns
        result = {"columns": module().get_columns(), "result": []}
        _remove_financial_columns(result)
        fields = {row["fieldname"] for row in result["columns"]}
        self.assertTrue({"capacity", "used_capacity", "available_capacity", "use_percentage"} <= fields)

    def test_capacity_unit_remains_visible_when_stock_filter_has_a_different_unit(self):
        self.assertIn("capacity_uom", {column["fieldname"] for column in module().get_columns()})
        rules = [dict(name="RULE", location="RACK-10", stock_capacity=100, stock_uom="PCS")]
        balances = self.balances()
        balances[2]["stock_uom"] = "KG"
        rows = module().build_tree(self.locations(), balances, dict(warehouse="WH", item_code="ITEM-B"), capacity_rules=rules)
        rack = next(row for row in rows if row["entry"] == "RACK-10")
        self.assertEqual((rack["capacity_uom"], rack["stock_uom"]), ("PCS", "KG"))
        self.assertIsNone(rack["used_capacity"])


def run_tests():
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(TestStorageLocationSummary)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise AssertionError("Storage Location Summary tests failed")
    return {"tests_run": result.testsRun, "successful": True}
