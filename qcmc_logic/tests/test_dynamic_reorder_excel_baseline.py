"""Excel baseline unit checks, no database writes."""
import unittest
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch
from qcmc_logic import dynamic_reorder_excel_baseline as b


class TestExcelBaseline(unittest.TestCase):
    def setup_data(self):
        terms = dict(sheet="QC", level="12.34", qty="20", lead_days="7",
                     safety_days="14", minimum="20", maximum="40")
        entries = {("I1", "FG - Sta Clara"): terms}
        plan = dict(ready=True, changes=[dict(item="i1", warehouse="FG - Sta Clara",
                    reorder_level="12.340", reorder_qty="20")],
                    exclusions=[dict(item="i1", reorder_level="12.34", reorder_qty="20")])
        return plan, entries

    def test_exact_values_and_case_insensitive_unique_match(self):
        plan, entries = self.setup_data()
        b.reconcile(plan, entries, ["i1"])
        self.assertEqual(plan["changes"][0]["reorder_level"], "12.340")

    def test_mismatch_fails(self):
        plan, entries = self.setup_data()
        plan["changes"][0]["reorder_qty"] = "21"
        with self.assertRaises(ValueError):
            b.reconcile(plan, entries, ["i1"])

    def test_ambiguous_item_fails(self):
        plan, entries = self.setup_data()
        with self.assertRaises(ValueError):
            b.reconcile(plan, entries, ["i1", "I1"])

    def test_preserved_guyong_mismatch_fails(self):
        plan, entries = self.setup_data()
        plan["exclusions"][0]["reorder_qty"] = "21"
        with self.assertRaises(ValueError):
            b.reconcile(plan, entries, ["i1"])

    def test_incomplete_and_duplicate_fail(self):
        plan, entries = self.setup_data()
        plan["changes"] = []
        with self.assertRaises(ValueError):
            b.reconcile(plan, entries, ["i1"])
        plan, entries = self.setup_data()
        plan["changes"] *= 2
        with self.assertRaises(ValueError):
            b.reconcile(plan, entries, ["i1"])

    def test_checksum_rejects_changed_workbook(self):
        with self.assertRaisesRegex(ValueError, "verified production baseline"):
            b.read_workbook(b"changed")

    def test_numeric_rejects_invalid_values(self):
        for value in ("NaN", "Infinity", -1, 0):
            with self.assertRaises(ValueError):
                b.numeric(value, True)

    def test_digest_binds_quantities_and_terms(self):
        plan, entries = self.setup_data()
        first = b.digest(plan)
        plan["changes"][0]["reorder_qty"] = "21"
        self.assertNotEqual(first, b.digest(plan))
        first = b.digest(entries[("I1", "FG - Sta Clara")])
        entries[("I1", "FG - Sta Clara")]["maximum"] = "41"
        self.assertNotEqual(first, b.digest(entries[("I1", "FG - Sta Clara")]))

    def test_exact_qc_terms_and_missing_mc_terms(self):
        _, entries = self.setup_data()
        terms = entries[("I1", "FG - Sta Clara")]
        snap = dict(workbook_sha256=b.CHECKSUM, approval_digest="reviewed", excel_terms=terms)
        history = SimpleNamespace(recommended_level=Decimal("12.340"), recommended_qty=20)
        self.assertEqual(b.baseline_replenishment_terms(snap, history),
            dict(excel_baseline=True, lead_time="7", minimum_stock="20", maximum_stock="40"))
        terms.update(sheet="MC", lead_days=None, minimum=None, maximum=None)
        self.assertIsNone(b.baseline_replenishment_terms(snap, history)["lead_time"])
        history.recommended_qty = 21
        with self.assertRaises(ValueError):
            b.baseline_replenishment_terms(snap, history)
