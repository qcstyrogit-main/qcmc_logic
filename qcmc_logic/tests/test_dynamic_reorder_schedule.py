"""Pure schedule boundary and validation tests."""
import unittest
from datetime import date,datetime,time,timedelta
from qcmc_logic.dynamic_reorder_schedule import (
    ZONE, schedule_values, latest_due, next_slot, following_slot, slot_time
)

def config(frequency="Monthly",**kwargs):
    return schedule_values(dict(frequency=frequency,execution_weekday="Monday",
        day_of_month=1,execution_time="02:00:00",maximum_retry_attempts=3) | kwargs)

class TestReorderSchedule(unittest.TestCase):
    def now(self,y,m,d,h=2,minute=0):
        return datetime(y,m,d,h,minute,tzinfo=ZONE)

    def test_month_boundary(self):
        c=config()
        self.assertEqual(latest_due(self.now(2026,12,1,1,59),c),date(2026,11,1))
        self.assertEqual(latest_due(self.now(2026,12,1),c),date(2026,12,1))
        self.assertEqual(next_slot(self.now(2026,12,1),c),date(2027,1,1))

    def test_daily(self):
        c=config("Daily",execution_time="14:30")
        self.assertEqual(latest_due(self.now(2026,11,25,14,29),c),date(2026,11,24))
        self.assertEqual(latest_due(self.now(2026,11,25,14,30),c),date(2026,11,25))
        self.assertEqual(next_slot(self.now(2026,11,25,14,30),c),date(2026,11,26))

    def test_weekly(self):
        c=config("Weekly")
        self.assertEqual(latest_due(self.now(2026,11,25),c),date(2026,11,23))
        self.assertEqual(next_slot(self.now(2026,11,25),c),date(2026,11,30))
        self.assertEqual(following_slot(date(2026,11,23),c),date(2026,11,30))

    def test_month_day(self):
        c=config(day_of_month=28)
        self.assertEqual(following_slot(date(2027,1,28),c),date(2027,2,28))

    def test_validation(self):
        for values in (dict(day_of_month=0),dict(day_of_month=29),dict(maximum_retry_attempts=0),dict(maximum_retry_attempts=11),dict(execution_time="02:00:01"),dict(execution_weekday="X")):
            with self.subTest(values=values),self.assertRaises(ValueError):
                config(**values)

    def test_database_time_type(self):
        c=config(execution_time=timedelta(hours=2))
        self.assertEqual(c[3],time(2))
        self.assertEqual(slot_time(date(2026,12,1),c).utcoffset(),timedelta(hours=8))
