from unittest import TestCase
from unittest.mock import patch

from frappe import _dict

from qcmc_logic.customs.daily_job_schedule import _validate_schedule_row, _validate_unique_shift


def schedule_row(**values):
    defaults = {
        "idx": 1,
        "process": "PROCESS-001",
        "msrp_no": "MSRP-001",
        "msjr_no": "MSJR-001",
        "quantity": 3,
    }
    defaults.update(values)
    return _dict(defaults)


def values_for(process_status="In Progress", workflow_state="Active", plan=5, done=2):
    def get_value(doctype, name, fieldnames, as_dict=False):
        if doctype == "Machine Shop Repairs and Project Process":
            return _dict(
                parent="MSRP-001",
                process_name="FABRICATING",
                status=process_status,
                plan_quantity=plan,
                done_quantity=done,
            )
        return _dict(workflow_state=workflow_state, msjr_no="MSJR-001")
    return get_value


class TestDailyJobScheduleValidation(TestCase):
    def test_rejects_duplicate_date_and_shift_on_server(self):
        doc = _dict(name="DJS-NEW", sched_date="2026-07-31", shift="DS")
        doc.is_new = lambda: True
        with (
            patch("qcmc_logic.customs.daily_job_schedule.frappe") as frappe,
            patch("qcmc_logic.customs.daily_job_schedule._", side_effect=lambda message: message),
        ):
            frappe.db.exists.return_value = "DJS-EXISTING"
            frappe.throw.side_effect = RuntimeError
            with self.assertRaises(RuntimeError):
                _validate_unique_shift(doc)

        self.assertIn("already exists", frappe.throw.call_args.args[0])

    def test_accepts_active_unfinished_process(self):
        with patch("qcmc_logic.customs.daily_job_schedule.frappe") as frappe:
            frappe.db.get_value.side_effect = values_for()
            _validate_schedule_row(schedule_row())

        frappe.throw.assert_not_called()

    def test_rejects_completed_process(self):
        with (
            patch("qcmc_logic.customs.daily_job_schedule.frappe") as frappe,
            patch("qcmc_logic.customs.daily_job_schedule._", side_effect=lambda message: message),
        ):
            frappe.db.get_value.side_effect = values_for(process_status="Completed", done=5)
            frappe.throw.side_effect = RuntimeError
            with self.assertRaises(RuntimeError):
                _validate_schedule_row(schedule_row(quantity=1))

        self.assertIn("completed", frappe.throw.call_args.args[0])

    def test_rejects_non_active_project(self):
        with (
            patch("qcmc_logic.customs.daily_job_schedule.frappe") as frappe,
            patch("qcmc_logic.customs.daily_job_schedule._", side_effect=lambda message: message),
        ):
            frappe.db.get_value.side_effect = values_for(workflow_state="Completed")
            frappe.throw.side_effect = RuntimeError
            with self.assertRaises(RuntimeError):
                _validate_schedule_row(schedule_row())

        self.assertIn("must be Active", frappe.throw.call_args.args[0])

    def test_rejects_quantity_above_remaining(self):
        with (
            patch("qcmc_logic.customs.daily_job_schedule.frappe") as frappe,
            patch("qcmc_logic.customs.daily_job_schedule._", side_effect=lambda message: message),
        ):
            frappe.db.get_value.side_effect = values_for(plan=5, done=2)
            frappe.throw.side_effect = RuntimeError
            with self.assertRaises(RuntimeError):
                _validate_schedule_row(schedule_row(quantity=4))

        self.assertIn("cannot exceed", frappe.throw.call_args.args[0])

    def test_rejects_process_project_mismatch(self):
        with (
            patch("qcmc_logic.customs.daily_job_schedule.frappe") as frappe,
            patch("qcmc_logic.customs.daily_job_schedule._", side_effect=lambda message: message),
        ):
            frappe.db.get_value.side_effect = values_for()
            frappe.throw.side_effect = RuntimeError
            with self.assertRaises(RuntimeError):
                _validate_schedule_row(schedule_row(msrp_no="MSRP-OTHER"))

        self.assertIn("does not belong", frappe.throw.call_args.args[0])
