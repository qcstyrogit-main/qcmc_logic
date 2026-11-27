from datetime import date
import unittest
from qcmc_logic.dynamic_reorder_policy import resolve_policy, eligible_category

class TestDynamicReorderPolicy(unittest.TestCase):
    def resolve(self, rows):
        return resolve_policy(rows, "Co", "I", ["FG", "All"], "W", ["Group"], date(2026, 11, 1))

    def test_specific_mapping(self):
        default = dict(enabled=1, company="Co", item_group="FG", policy="default")
        specific = dict(enabled=1, company="Co", item_code="I", warehouse="W", policy="specific")
        self.assertEqual(self.resolve([default, specific])["policy"], "specific")

    def test_conflict(self):
        row = dict(enabled=1, company="Co", warehouse="W", policy="A")
        with self.assertRaises(ValueError):
            self.resolve([row, dict(row, policy="B")])

    def test_disabled_and_other_company(self):
        self.assertIsNone(self.resolve([dict(enabled=0, company="Co", warehouse="W"),
                                        dict(enabled=1, company="Other", warehouse="W")]))

    def test_descendant_opt_in(self):
        row = dict(enabled=1, company="Co", item_group="All", warehouse="Group")
        self.assertIsNone(self.resolve([row]))
        self.assertIsNotNone(self.resolve([dict(row, include_item_descendants=1, include_warehouse_descendants=1)]))

    def test_only_finished_goods(self):
        self.assertTrue(eligible_category(dict(enabled=1, inventory_category="FG")))
        self.assertFalse(eligible_category(dict(enabled=1, inventory_category="Raw Materials")))
