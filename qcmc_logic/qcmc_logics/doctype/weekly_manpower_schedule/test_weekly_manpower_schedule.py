import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from qcmc_logic.qcmc_logics.doctype.weekly_manpower_schedule.weekly_manpower_schedule import (
	DAY_FIELDS,
	SHIFT_HALVES,
	VALID_DAY_STATUSES,
	WeeklyManpowerSchedule,
	get_checked_date_ranges,
	has_excluded_cost_center_marker,
	normalize_day_status,
	sort_schedule_detail_rows,
)


class TestWeeklyManpowerSchedule(unittest.TestCase):
	def test_workbench_save_can_skip_parent_section_validation(self):
		calls = []
		schedule = SimpleNamespace(
			flags={"skip_section_validation": True},
			_validate_week=lambda: calls.append("week"),
			_validate_section=lambda: calls.append("section"),
			_validate_rows=lambda: calls.append("rows"),
		)

		WeeklyManpowerSchedule.validate(schedule)

		self.assertEqual(calls, ["week", "rows"])

	def test_normal_save_still_validates_parent_section(self):
		calls = []
		schedule = SimpleNamespace(
			flags={},
			_validate_week=lambda: calls.append("week"),
			_validate_section=lambda: calls.append("section"),
			_validate_rows=lambda: calls.append("rows"),
		)

		WeeklyManpowerSchedule.validate(schedule)

		self.assertEqual(calls, ["week", "section", "rows"])

	def test_checked_days_are_grouped_into_contiguous_ranges(self):
		self.assertEqual(
			get_checked_date_ranges(
				"2026-10-19",
				["Check", "NW", "V", "v", "RD", "Check", "NW"],
			),
			[
				(date(2026, 10, 19), date(2026, 10, 19)),
				(date(2026, 10, 21), date(2026, 10, 22)),
				(date(2026, 10, 24), date(2026, 10, 24)),
			],
		)

	def test_no_checked_days_create_no_assignment_ranges(self):
		self.assertEqual(get_checked_date_ranges("2026-10-19", ["NW", "RD", "PW", "X", "NW", "RD", "X"]), [])

	def test_new_weekday_statuses_are_valid(self):
		self.assertEqual(VALID_DAY_STATUSES, {"PW", "NW", "RD", "X"})

	def test_detail_rows_sort_by_company_location_and_natural_order_key(self):
		rows = [
			SimpleNamespace(location="10", sortingno="20A"),
			SimpleNamespace(location="2", sortingno="100A"),
			SimpleNamespace(location="2", sortingno="20A"),
			SimpleNamespace(location="1", sortingno="300A"),
		]

		sorted_rows = sort_schedule_detail_rows(rows, "Multiplast Corporation")

		self.assertEqual(
			[(row.location, row.sortingno) for row in sorted_rows],
			[("1", "300A"), ("2", "20A"), ("2", "100A"), ("10", "20A")],
		)

	def test_blank_day_status_defaults_to_x(self):
		self.assertEqual(normalize_day_status(""), "X")
		self.assertEqual(normalize_day_status("  "), "X")
		self.assertEqual(normalize_day_status(None), "X")

	def test_day_status_is_normalized_and_validated(self):
		for status in ("PW", "NW", "RD", "X"):
			self.assertEqual(normalize_day_status(status.lower()), status)
		with self.assertRaises(ValueError):
			normalize_day_status("Check")

	def test_row_validation_replaces_blank_statuses_with_x(self):
		class ScheduleRow:
			idx = 1

			def __init__(self):
				self.values = {
					f"{shift}_{day}": ""
					for shift in SHIFT_HALVES
					for day in DAY_FIELDS
				}

			def get(self, fieldname):
				return self.values.get(fieldname)

			def set(self, fieldname, value):
				self.values[fieldname] = value

		row = ScheduleRow()
		schedule = SimpleNamespace(schedule_details=[row], workflow_state="Draft")

		WeeklyManpowerSchedule._validate_rows(schedule)

		self.assertEqual(set(row.values.values()), {"X"})

	def test_row_validation_rejects_invalid_statuses_for_each_day_and_shift(self):
		class ScheduleRow:
			idx = 1

			def __init__(self, invalid_field):
				self.values = {
					f"{shift}_{day}": "X"
					for shift in SHIFT_HALVES
					for day in DAY_FIELDS
				}
				self.values[invalid_field] = "Check"

			def get(self, fieldname):
				return self.values.get(fieldname)

			def set(self, fieldname, value):
				self.values[fieldname] = value

		for shift in SHIFT_HALVES:
			for day in DAY_FIELDS:
				with self.subTest(shift=shift, day=day):
					row = ScheduleRow(f"{shift}_{day}")
					schedule = SimpleNamespace(schedule_details=[row], workflow_state="Draft")
					with (
						patch(
							"qcmc_logic.qcmc_logics.doctype.weekly_manpower_schedule.weekly_manpower_schedule._",
							side_effect=lambda message: message,
						),
						patch(
							"qcmc_logic.qcmc_logics.doctype.weekly_manpower_schedule.weekly_manpower_schedule.frappe.throw",
							side_effect=ValueError,
						),
					):
						with self.assertRaises(ValueError):
							WeeklyManpowerSchedule._validate_rows(schedule)

	def test_v_markers_are_scheduled_days_case_insensitively(self):
		self.assertEqual(
			get_checked_date_ranges("2026-10-19", ["v", "NW", "RD", "Check", "NW", "RD", "NW"]),
			[(date(2026, 10, 19), date(2026, 10, 19)), (date(2026, 10, 22), date(2026, 10, 22))],
		)

	def test_dash_marker_does_not_create_an_assignment(self):
		self.assertEqual(get_checked_date_ranges("2026-10-19", ["-"] * 7), [])

	def test_cost_center_markers_are_case_insensitive(self):
		self.assertTrue(has_excluded_cost_center_marker("Packaging EPS Department"))
		self.assertTrue(has_excluded_cost_center_marker("PSP Section"))
		self.assertFalse(has_excluded_cost_center_marker("Thermoforming"))
		self.assertFalse(has_excluded_cost_center_marker("Steps Department"))


if __name__ == "__main__":
	unittest.main()