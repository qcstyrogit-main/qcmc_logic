"""Read-only migration inventory tests; no site or database required."""
import unittest
from qcmc_logic.dynamic_reorder_adoption import inventory_plan, mapping_plan, GROUPS, PRESERVED


class TestReorderAdoptionInventory(unittest.TestCase):
    def row(self, name="R1", warehouse="FG - Sta Clara", **kwargs):
        row = dict(name=name, parent="I1", warehouse=warehouse, warehouse_group=warehouse,
            material_request_type="Manufacture", warehouse_reorder_level=10,
            warehouse_reorder_qty=20, inventory_group="FG", inventory_type="Local",
            warehouse_company="QC Styropackaging Corporation", is_stock_item=1,
            custom_managed_reorder=0)
        row.update(kwargs)
        return row

    def plan(self, rows):
        return inventory_plan(rows, {"FG - Sta Clara": (1, "Manufacture")},
                              {"FG - Guyong": (1, "Manufacture")})

    def mapping(self, **kwargs):
        data = dict(name="M", company="QC Styropackaging Corporation", enabled=1,
            policy_enabled=1, inventory_group="FG", inventory_type="Local",
            request_type="Preserve", replenishment_warehouse="FG - Sta Clara",
            warehouses=["FG - Sta Clara","FG - Guyong"], automatic_draft_replenishment=0)
        data.update(kwargs)
        return data

    def test_mapping_plan_and_preserved_marker(self):
        inv = self.plan([self.row(), self.row("G1","FG - Guyong")])
        plan = mapping_plan(inv, [self.mapping()])
        self.assertTrue(plan["ready"])
        self.assertEqual(plan["count"],1)
        self.assertEqual(plan["exclusion_count"],1)
        self.assertEqual(plan["exclusions"][0]["mapping"],"M")
        self.assertEqual(plan["digest"],mapping_plan(inv,[self.mapping()])["digest"])
        inv["candidates"][0]["reorder_qty"]="21"
        self.assertNotEqual(plan["digest"],mapping_plan(inv,[self.mapping()])["digest"])

    def test_missing_or_unsafe_mapping_blocks_adoption(self):
        inv = self.plan([self.row(),self.row("G1","FG - Guyong")])
        for mappings in ([], [self.mapping(automatic_draft_replenishment=1)],
                         [self.mapping(warehouses=["FG - Sta Clara"])],
                         [self.mapping(request_type="Purchase")],
                         [self.mapping(),self.mapping(name="M2")]):
            self.assertFalse(mapping_plan(inv,mappings)["ready"])

    def test_expected_production_counts(self):
        self.assertEqual(sum(n for n,t in GROUPS.values()), 881)
        self.assertEqual(sum(n for n,t in PRESERVED.values()), 209)
        self.assertEqual(sum(n for n,t in GROUPS.values() if t=="Transfer"),470)

    def test_plan_preserves_values_and_guyong(self):
        rows = [self.row(), self.row("G1", "FG - Guyong")]
        original = [dict(r) for r in rows]
        result = self.plan(rows)
        self.assertTrue(result["ready_for_mapping_review"])
        self.assertEqual(result["eligible"],1)
        self.assertEqual(result["preserved_rows"],["G1"])
        self.assertEqual(result["candidates"][0]["reorder_level"],"10")
        self.assertEqual(result["candidates"][0]["reorder_qty"],"20")
        self.assertEqual(rows,original)

    def test_missing_counterpart_and_count_mismatch_block_review(self):
        result = self.plan([self.row("G1","FG - Guyong")])
        self.assertFalse(result["ready_for_mapping_review"])
        self.assertTrue(result["count_differences"])
        self.assertIn("counterpart",str(result["issues"]))

    def test_duplicate_invalid_classification_and_negative_values_block_review(self):
        result = self.plan([self.row(),self.row("R2",inventory_type=None,
                           warehouse_reorder_qty=-1),self.row("G1","FG - Guyong")])
        self.assertFalse(result["ready_for_mapping_review"])
        self.assertEqual(result["eligible"],0)
        for reason in ("Duplicate","classification","Invalid reorder values"):
            self.assertIn(reason,str(result["issues"]))

    def test_partial_ownership_blocks_review(self):
        result = self.plan([self.row(custom_reorder_mapping="M"),self.row("G1","FG - Guyong")])
        self.assertFalse(result["ready_for_mapping_review"])
        self.assertIn("ownership",str(result["issues"]))

    def test_existing_managed_row_not_adopted_again(self):
        result = self.plan([self.row(custom_reorder_mapping="M",custom_managed_reorder=1),
                            self.row("G1","FG - Guyong")])
        self.assertEqual(result["eligible"],0)
        self.assertEqual(result["already_managed"],1)

    def test_wrong_company_blocks_review(self):
        result = self.plan([self.row(warehouse_company="Multiplast Corporation"),
                            self.row("G1","FG - Guyong")])
        self.assertFalse(result["ready_for_mapping_review"])
        self.assertIn("company",str(result["issues"]))
