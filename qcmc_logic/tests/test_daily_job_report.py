from unittest import TestCase
from unittest.mock import patch

from frappe import _dict

from qcmc_logic.customs.daily_job_report import _find_scheduled_work, _validate_reported_quantity


def schedule_row(**values):
    defaults = {
        "row_name": "ROW-1",
        "schedule_name": "DJS-1",
        "employee": "EMP-1",
        "quantity": 5,
        "sched_date": "2026-08-03",
        "time_from": "07:00:00",
        "time_to": "19:00:00",
        "shift": "DS",
    }
    defaults.update(values)
    return _dict(defaults)


def report(**values):
    defaults = {
        "name": "DJR-NEW",
        "process_no": "PROCESS-1",
        "worked_by": "EMP-1",
        "date_started": "2026-08-03 08:00:00",
        "date_finished": "2026-08-03 17:00:00",
        "quantity": 1,
    }
    defaults.update(values)
    return _dict(defaults)


class TestDailyJobReportScheduleValidation(TestCase):
    def test_accepts_zero_quantity(self):
        doc = report(quantity=0)
        with patch("qcmc_logic.customs.daily_job_report.frappe") as frappe:
            frappe.db.sql.return_value = [(0,), (0,)]
            _validate_reported_quantity(
                doc,
                _dict(plan_quantity=10),
                _dict(quantity=5, window_start="2026-08-03 07:00:00", window_end="2026-08-03 19:00:00"),
            )

        frappe.throw.assert_not_called()

    def test_rejects_negative_quantity(self):
        doc = report(quantity=-1)
        with (
            patch("qcmc_logic.customs.daily_job_report.frappe") as frappe,
            patch("qcmc_logic.customs.daily_job_report._", side_effect=lambda message: message),
        ):
            frappe.throw.side_effect = RuntimeError
            with self.assertRaises(RuntimeError):
                _validate_reported_quantity(doc, _dict(plan_quantity=10))

        self.assertIn("cannot be negative", frappe.throw.call_args.args[0])

    def test_finds_matching_engineering_schedule_without_djr_link_field(self):
        with patch("qcmc_logic.customs.daily_job_report.frappe") as frappe:
            frappe.db.get_value.return_value = "MSJR-1"
            frappe.db.sql.return_value = [schedule_row()]

            row = _find_scheduled_work(report(), _dict(parent="MSRP-1"))

        self.assertEqual(row.schedule_name, "DJS-1")

    def test_accepts_night_shift_across_midnight(self):
        doc = report(
            date_started="2026-08-03 20:00:00",
            date_finished="2026-08-04 06:00:00",
        )
        with patch("qcmc_logic.customs.daily_job_report.frappe") as frappe:
            frappe.db.get_value.return_value = "MSJR-1"
            frappe.db.sql.return_value = [
                schedule_row(time_from="19:00:00", time_to="07:00:00", shift="NS")
            ]

            row = _find_scheduled_work(doc, _dict(parent="MSRP-1"))

        self.assertEqual(row.schedule_name, "DJS-1")

    def test_rejects_date_time_outside_schedule(self):
        doc = report(date_started="2026-08-03 06:30:00")
        with (
            patch("qcmc_logic.customs.daily_job_report.frappe") as frappe,
            patch("qcmc_logic.customs.daily_job_report._", side_effect=lambda message: message),
        ):
            frappe.db.get_value.return_value = "MSJR-1"
            frappe.db.sql.return_value = [schedule_row()]
            frappe.throw.side_effect = RuntimeError
            with self.assertRaises(RuntimeError):
                _find_scheduled_work(doc, _dict(parent="MSRP-1"))

        self.assertIn("No Engineering Daily Job Schedule", frappe.throw.call_args.args[0])

    def test_rejects_when_msjr_process_has_no_schedule_row(self):
        with (
            patch("qcmc_logic.customs.daily_job_report.frappe") as frappe,
            patch("qcmc_logic.customs.daily_job_report._", side_effect=lambda message: message),
        ):
            frappe.db.get_value.return_value = "MSJR-1"
            frappe.db.sql.return_value = []
            frappe.throw.side_effect = RuntimeError
            with self.assertRaises(RuntimeError):
                _find_scheduled_work(report(), _dict(parent="MSRP-1"))

        self.assertIn("No Engineering Daily Job Schedule", frappe.throw.call_args.args[0])

    def test_rejects_different_scheduled_employee(self):
        with (
            patch("qcmc_logic.customs.daily_job_report.frappe") as frappe,
            patch("qcmc_logic.customs.daily_job_report._", side_effect=lambda message: message),
        ):
            frappe.db.get_value.return_value = "MSJR-1"
            frappe.db.sql.return_value = [schedule_row(employee="EMP-OTHER")]
            frappe.throw.side_effect = RuntimeError
            with self.assertRaises(RuntimeError):
                _find_scheduled_work(report(), _dict(parent="MSRP-1"))

        self.assertIn("No Engineering Daily Job Schedule", frappe.throw.call_args.args[0])

    def test_rejects_quantity_above_remaining_process_plan(self):
        doc = report(quantity=4)
        with (
            patch("qcmc_logic.customs.daily_job_report.frappe") as frappe,
            patch("qcmc_logic.customs.daily_job_report._", side_effect=lambda message: message),
        ):
            frappe.db.sql.return_value = [(7,)]
            frappe.throw.side_effect = RuntimeError
            with self.assertRaises(RuntimeError):
                _validate_reported_quantity(doc, _dict(plan_quantity=10))

        self.assertIn("exceeds", frappe.throw.call_args.args[0])
