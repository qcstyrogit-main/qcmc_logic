from datetime import date
from decimal import Decimal
import unittest
from qcmc_logic.dynamic_reorder_calculation import demand_period, calculate

class TestDemandPeriod(unittest.TestCase):
    def test_rolling_90(self):
        as_of=date(2026,11,24)
        periods=demand_period(as_of,"Rolling Days",rolling_days=90)
        self.assertEqual(periods[0][0],date(2026,8,26))
        self.assertEqual(periods[-1][1],date(2026,11,23))
        self.assertEqual(sum((b-a).days+1 for a,b in periods),90)
        history={a.replace(day=1):4000 if a.month==11 else 0 for a,b in periods}
        result=calculate(as_of,history,periods=periods)
        self.assertEqual(result["reorder_level"],534)
        self.assertEqual(result["reorder_qty"],667)
    def test_mtd(self):
        p=demand_period(date(2026,11,24),"Month-to-Date Inclusive",3)
        self.assertEqual(p[0][0],date(2026,8,1))
        self.assertEqual(p[-1][1],date(2026,11,23))
        self.assertEqual(sum((b-a).days+1 for a,b in p),115)
    def test_first_day(self):
        self.assertEqual(demand_period(date(2026,12,1),"Month-to-Date Inclusive",3),
                         demand_period(date(2026,12,1)))
    def test_leap_day(self):
        self.assertEqual(demand_period(date(2024,3,1),"Rolling Days",rolling_days=1),
                         [(date(2024,2,29),date(2024,2,29))])
    def test_invalid_rolling(self):
        with self.assertRaises(ValueError):
            demand_period(date(2026,11,24),"Rolling Days",rolling_days=0)
    def test_seasonal_partial_month(self):
        p=demand_period(date(2026,11,24),"Rolling Days",rolling_days=10)
        r=calculate(date(2026,11,24),{date(2026,11,1):100},periods=p,indices={m:1 for m in range(1,13)})
        self.assertEqual(r["historical_days"],10)
        self.assertEqual(r["average_daily"],Decimal(10))
