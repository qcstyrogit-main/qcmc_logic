from datetime import date
from decimal import Decimal
import unittest
from qcmc_logic.dynamic_reorder_calculation import historical_months, calculate, seasonal_indices, round_up


class TestDynamicReorderCalculation(unittest.TestCase):
    def test_complete_months_leap(self):
        self.assertEqual(historical_months(date(2024, 3, 15))[-1],
                         (date(2024, 2, 1), date(2024, 2, 29)))

    def test_default_formula(self):
        history = {date(2026, 8, 1): 310, date(2026, 9, 1): 300, date(2026, 10, 1): 310}
        result = calculate(date(2026, 11, 1), history, previous_level=120, previous_qty=150)
        self.assertEqual(result["reorder_level"], 120)
        self.assertEqual(result["reorder_qty"], 150)
        self.assertEqual(result["status"], "Preview")

    def test_zero_demand(self):
        self.assertEqual(calculate(date(2026, 11, 1), {date(2026, 10, 1): 0})["status"], "Skipped")

    def test_batch_multiple(self):
        self.assertEqual(round_up(101, 12, 10, 1), 120)

    def test_seasonal_fallback(self):
        self.assertIsNone(seasonal_indices([(date(2026, 1, 1), 100)]))

    def test_seasonal_cross_month(self):
        factors = {m: 1 for m in range(1, 13)}
        factors[12] = 2
        result = calculate(date(2026, 11, 29), {date(2026, 10, 1): 310},
                           lead=4, safety=0, coverage=4, indices=factors)
        self.assertEqual(result["reorder_level"], 60)
        self.assertEqual(result["status"], "Pending Approval")

    def test_maximum_review(self):
        result = calculate(date(2026, 11, 1), {date(2026, 10, 1): 310},
                           maximum=100, previous_level=120, previous_qty=150)
        self.assertEqual(result["status"], "Pending Approval")
