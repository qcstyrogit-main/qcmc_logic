"""Read-only business date boundaries for catch-up scheduler."""
from datetime import datetime, date
from zoneinfo import ZoneInfo
from qcmc_logic.dynamic_reorder_scheduler import due_date

def run():
    zone=ZoneInfo("Asia/Manila")
    for day,hour,minute,expected in [(1,1,59,date(2026,11,1)),(1,2,0,date(2026,12,1)),(1,2,59,date(2026,12,1)),(1,3,0,date(2026,12,1)),(2,2,0,date(2026,12,1))]:
        assert due_date(datetime(2026,12,day,hour,minute,tzinfo=zone))==expected
    return ["PASS: Philippine 2 AM cutoff and late catch-up date"]

