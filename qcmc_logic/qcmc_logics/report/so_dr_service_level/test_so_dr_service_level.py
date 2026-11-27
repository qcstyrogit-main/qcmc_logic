from datetime import date
from decimal import Decimal
from unittest import TestCase

from qcmc_logic.qcmc_logics.report.so_dr_service_level.so_dr_service_level import evaluate


class TestSODRServiceLevel(TestCase):
    def test_staggered_late_delivery(self):
        due = date(2026, 11, 10)
        events = [(date(2026, 11, d), Decimal(200000)) for d in range(10, 15)]
        row = evaluate(Decimal(1000000), events, due, date(2026, 11, 25))
        self.assertEqual(row["on_time_qty"], 200000)
        self.assertEqual(row["late_qty"], 800000)
        self.assertEqual(row["delivered_qty"], 1000000)
        self.assertEqual(row["open_qty"], 0)
        self.assertEqual(row["otif"], "Delivered Late")

    def test_short_delivery_not_yet_completed(self):
        row = evaluate(Decimal(10000), [(date(2026, 11, 12), Decimal(5000))],
                       date(2026, 11, 12), date(2026, 11, 25))
        self.assertEqual(row["otif"], "Overdue Partial")
        self.assertEqual(row["open_qty"], 5000)

    def test_undelivered_order(self):
        row = evaluate(Decimal(1000), [], date(2026, 11, 21), date(2026, 11, 25))
        self.assertEqual(row["otif"], "Overdue Undelivered")
        self.assertEqual(row["open_qty"], 1000)

    def test_full_on_time(self):
        row = evaluate(Decimal(1000), [(date(2026, 11, 21), Decimal(1000))],
                       date(2026, 11, 21), date(2026, 11, 25))
        self.assertEqual(row["otif"], "Pass")
        self.assertEqual(row["on_time"], "Yes")
        self.assertEqual(row["in_full"], "Yes")

    def test_current_day_and_future_excluded(self):
        row = evaluate(Decimal(1000), [], date(2026, 11, 25), date(2026, 11, 25))
        self.assertEqual(row["otif"], "Not Yet Due")
        row = evaluate(Decimal(1000), [], date(2026, 11, 26), date(2026, 11, 25))
        self.assertEqual(row["otif"], "Not Yet Due")

    def test_future_posting_not_counted(self):
        row = evaluate(Decimal(1000), [(date(2026, 11, 26), Decimal(1000))],
                       date(2026, 11, 21), date(2026, 11, 25))
        self.assertEqual(row["delivered_qty"], 0)
        self.assertEqual(row["otif"], "Overdue Undelivered")
