"""Scheduler state-machine tests use only in-memory execution documents."""
import unittest
from contextlib import ExitStack
from datetime import date, datetime
from unittest.mock import patch, MagicMock
import frappe
from qcmc_logic import dynamic_reorder_scheduler as s
from qcmc_logic.dynamic_reorder_schedule import ZONE


class Doc(frappe._dict):
    def as_dict(self): return dict(self)
    def insert(self,**kwargs): return self


class TestSchedulerState(unittest.TestCase):
    def setUp(self):
        self.stack=ExitStack(); self.addCleanup(self.stack.close)
        self.runs={}
        self.settings=Doc(enabled=1,preview_only=0,automatic_update_enabled=1)
        self.schedule=Doc(enabled=1,frequency="Monthly",execution_weekday="Monday",day_of_month=1,
            execution_time="02:00:00",maximum_retry_attempts=3,recover_missed_executions=1,effective_from=date(2026,12,1))
        db=MagicMock(); db.exists.side_effect=lambda dt,filters: True if dt=="DocType" else any(r.scheduled_date==filters["scheduled_date"] for r in self.runs.values())
        db.get_value.side_effect=lambda dt,filters,*a,**kw: next((r.name for r in self.runs.values() if r.scheduled_date==filters["scheduled_date"]),None)
        db.set_value.side_effect=lambda dt,name,values: self.runs[name].update(values)
        for key,value in (("db",db),("session",Doc(user="Administrator")),("cache",MagicMock())):
            self.stack.enter_context(patch.object(frappe,key,value))
        self.stack.enter_context(patch.object(frappe,"get_single",return_value=self.settings))
        self.stack.enter_context(patch.object(frappe,"get_all",side_effect=self.get_all))
        self.stack.enter_context(patch.object(frappe,"get_doc",side_effect=self.get_doc))
        self.stack.enter_context(patch.object(s,"get_schedule",return_value=self.schedule))
        self.stack.enter_context(patch("frappe.utils.now_datetime",return_value=datetime(2026,12,1,2)))
        self.clock=self.stack.enter_context(patch.object(s,"business_now",return_value=datetime(2026,12,1,2,tzinfo=ZONE)))
        self.process=self.stack.enter_context(patch.object(s,"process_month",return_value=dict(failed=0)))
        self.stack.enter_context(patch.object(s,"safe_notify"))
        self.stack.enter_context(patch.object(s,"notify_run"))

    def get_doc(self,dt,name=None):
        if isinstance(dt,dict):
            doc=Doc(dt); doc.name="H"+str(len(self.runs)); doc.attempts=doc.get("attempts") or 0
            self.runs[doc.name]=Doc(dict(doc)); return doc
        return Doc(dict(self.runs[name]))

    def get_all(self,dt,**kwargs):
        if kwargs.get("pluck"): return []
        rows=sorted(self.runs.values(),key=lambda r:r.scheduled_date,reverse=True)
        return rows[:1]

    def test_disabled_and_future_baseline_do_not_run(self):
        self.settings.enabled=0
        self.assertEqual(s.monthly()["status"],"Disabled")
        self.settings.enabled=1; self.clock.return_value=datetime(2026,12,1,1,59,tzinfo=ZONE)
        self.assertEqual(s.monthly()["status"],"Awaiting First Schedule")
        self.process.assert_not_called()

    def test_success_is_persistent_and_always_preview_only(self):
        self.assertEqual(s.monthly()["status"],"Completed")
        effective,as_of=self.process.call_args.args
        self.assertTrue(effective.preview_only); self.assertFalse(effective.automatic_update_enabled)
        self.assertEqual(as_of,date(2026,12,1))
        self.assertEqual(s.monthly()["status"],"Completed")
        self.process.assert_called_once()

    def test_three_failures_stop_retries(self):
        self.process.return_value=dict(failed=1)
        for status in ("Retry Pending","Retry Pending","Failed - Review Required","Failed - Review Required"):
            self.assertEqual(s.monthly()["status"],status)
        self.assertEqual(self.process.call_count,3)

    def test_latest_missed_slot_only_is_recovered(self):
        self.clock.return_value=datetime(2027,2,2,10,tzinfo=ZONE)
        result=s.monthly()
        self.assertEqual(result["status"],"Completed"); self.assertTrue(result["catch_up"])
        self.assertEqual(sum(r.status=="Missed - Superseded" for r in self.runs.values()),2)
        self.assertEqual(self.process.call_args.args[1],date(2027,2,1))
