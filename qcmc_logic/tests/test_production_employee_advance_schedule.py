from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

import frappe

from qcmc_logic.qcmc_logics.doctype.production_employee_advance_schedule.production_employee_advance_schedule import (
	_make_interval,
	_validate_overlapping_assignments,
	get_approver_roles_for_company,
	get_creator_roles_for_company,
	validate_week_dates,
)


APP_ROOT = Path(__file__).resolve().parents[2]


class TestProductionEmployeeAdvanceScheduleRules(TestCase):
	def test_company_role_routing(self):
		self.assertEqual(
			get_creator_roles_for_company("Multiplast Corporation"),
			{"Production - MC"},
		)
		self.assertEqual(
			get_approver_roles_for_company("Multiplast Corporation"),
			{"Plant Manager MC"},
		)
		self.assertEqual(
			get_creator_roles_for_company("QC Styropackaging Corporation"),
			{"Production - SMB", "Production - STCLA"},
		)
		self.assertEqual(
			get_approver_roles_for_company("QC Styropackaging Corporation"),
			{"Plant Manager QC"},
		)

	def test_week_accepts_monday_through_sunday(self):
		validate_week_dates("2026-07-20", "2026-07-26")

	def test_week_rejects_non_monday_start(self):
		with patch(
			"qcmc_logic.qcmc_logics.doctype.production_employee_advance_schedule.production_employee_advance_schedule.frappe.throw",
			side_effect=frappe.ValidationError,
		):
			with self.assertRaises(frappe.ValidationError):
				validate_week_dates("2026-07-21", "2026-07-26")

	def test_week_rejects_more_than_seven_days(self):
		with patch(
			"qcmc_logic.qcmc_logics.doctype.production_employee_advance_schedule.production_employee_advance_schedule.frappe.throw",
			side_effect=frappe.ValidationError,
		):
			with self.assertRaises(frappe.ValidationError):
				validate_week_dates("2026-07-20", "2026-07-27")

	def test_overnight_shift_ends_on_following_date(self):
		start, end = _make_interval(
			date(2026, 7, 20),
			timedelta(hours=18),
			timedelta(hours=6),
		)
		self.assertEqual(start, datetime(2026, 7, 20, 18, 0))
		self.assertEqual(end, datetime(2026, 7, 21, 6, 0))

	def test_position_move_on_different_days_does_not_conflict(self):
		_validate_overlapping_assignments(
			[
				{
					"employee": "EMP-001",
					"start": datetime(2026, 7, 20, 6),
					"end": datetime(2026, 7, 20, 18),
					"row": 1,
					"fieldname": "day_shift_mon",
				},
				{
					"employee": "EMP-001",
					"start": datetime(2026, 7, 22, 6),
					"end": datetime(2026, 7, 22, 18),
					"row": 2,
					"fieldname": "day_shift_wed",
				},
			]
		)

	def test_overlapping_position_assignments_are_rejected(self):
		with patch(
			"qcmc_logic.qcmc_logics.doctype.production_employee_advance_schedule.production_employee_advance_schedule.frappe.throw",
			side_effect=frappe.ValidationError,
		):
			with self.assertRaises(frappe.ValidationError):
				_validate_overlapping_assignments(
					[
						{
							"employee": "EMP-001",
							"start": datetime(2026, 7, 20, 6),
							"end": datetime(2026, 7, 20, 18),
							"row": 1,
							"fieldname": "day_shift_mon",
						},
						{
							"employee": "EMP-001",
							"start": datetime(2026, 7, 20, 12),
							"end": datetime(2026, 7, 20, 20),
							"row": 2,
							"fieldname": "day_shift_mon",
						},
					]
				)


class TestProductionScheduleMetadata(TestCase):
	def test_detail_contains_complete_day_and_night_week(self):
		path = (
			APP_ROOT
			/ "qcmc_logic"
			/ "qcmc_logics"
			/ "doctype"
			/ "production_employee_schedule_detail"
			/ "production_employee_schedule_detail.json"
		)
		doc = json.loads(path.read_text(encoding="utf-8"))
		fieldnames = {field["fieldname"] for field in doc["fields"]}
		plantilla_link = next(
			field for field in doc["fields"] if field["fieldname"] == "production_plantilla"
		)
		self.assertEqual(plantilla_link["fieldtype"], "Link")
		self.assertEqual(plantilla_link["options"], "Production Plantilla")
		self.assertEqual(plantilla_link["in_list_view"], 1)
		for prefix in ("day_shift", "night_shift"):
			for day in ("mon", "tue", "wed", "thu", "fri", "sat", "sun"):
				self.assertIn(f"{prefix}_{day}", fieldnames)
		self.assertIn("day_shift_restday", fieldnames)
		self.assertIn("night_shift_restday", fieldnames)

	def test_warehouse_event_auto_populates_without_saving(self):
		path = (
			APP_ROOT
			/ "qcmc_logic"
			/ "qcmc_logics"
			/ "doctype"
			/ "production_employee_advance_schedule"
			/ "production_employee_advance_schedule.js"
		)
		script = path.read_text(encoding="utf-8")
		self.assertIn("async warehouse(frm)", script)
		self.assertIn("await populate_plantilla(frm", script)
		self.assertIn('frm.add_child("schedule_details"', script)
		self.assertNotIn("frm.save(", script)

	def test_workflow_has_company_specific_approval_and_hr_posting(self):
		workflows = json.loads(
			(APP_ROOT / "qcmc_logic" / "fixtures" / "workflow.json").read_text(encoding="utf-8")
		)
		workflow = next(
			row
			for row in workflows
			if row["name"] == "Production Employee Advance Schedule Workflow"
		)
		transitions = {
			(
				row["state"],
				row["action"],
				row["allowed"],
				row["next_state"],
				row.get("condition"),
			)
			for row in workflow["transitions"]
		}
		self.assertIn(
			(
				"For Approval",
				"Approve",
				"Plant Manager MC",
				"Approved for Posting",
				'doc.company == "Multiplast Corporation"',
			),
			transitions,
		)
		self.assertIn(
			(
				"For Approval",
				"Approve",
				"Plant Manager QC",
				"Approved for Posting",
				'doc.company == "QC Styropackaging Corporation"',
			),
			transitions,
		)
		self.assertIn(
			(
				"Approved for Posting",
				"Post Schedule",
				"HR User",
				"Posted / Active",
				None,
			),
			transitions,
		)


class TestProductionScheduleIntegration(TestCase):
	def test_draft_schedule_with_plantilla_row_inserts(self):
		required_records = (
			("Company", "QC Styropackaging Corporation"),
			("Warehouse", "RMFS - Guyong"),
			("Plant Floor", "CPS"),
			("Workstation", "AVM1"),
			("Shift Type", "Shift Type 1"),
		)
		if not all(frappe.db.exists(doctype, name) for doctype, name in required_records):
			self.skipTest("Production schedule reference masters are not available on this test site.")

		savepoint = "production_schedule_integration"
		frappe.db.savepoint(savepoint)
		try:
			next_id = (
				frappe.db.sql(
					"select coalesce(max(plantilla_id), 0) + 1000 from `tabProduction Plantilla`"
				)[0][0]
				or 1000
			)
			plantilla = frappe.get_doc(
				{
					"doctype": "Production Plantilla",
					"plantilla_id": next_id,
					"company": "QC Styropackaging Corporation",
					"warehouse": "RMFS - Guyong",
					"section": "CPS",
					"machine": "AVM1",
					"production_position": "TEST OPERATOR",
					"plantilla_slot": 1,
					"is_active": 1,
				}
			).insert(ignore_permissions=True)

			row = {
				"section": plantilla.section,
				"machine": plantilla.machine,
				"production_position": plantilla.production_position,
				"plantilla_id": plantilla.plantilla_id,
				"plantilla_slot": plantilla.plantilla_slot,
				"row_source": "Plantilla",
				"production_plantilla": plantilla.name,
				"ds_assignment_status": "PLAN STOP",
				"ns_assignment_status": "PLAN STOP",
			}
			for prefix in ("day_shift", "night_shift"):
				for day in ("mon", "tue", "wed", "thu", "fri", "sat", "sun"):
					row[f"{prefix}_{day}"] = "Shift Type 1"

			schedule = frappe.get_doc(
				{
					"doctype": "Production Employee Advance Schedule",
					"company": "QC Styropackaging Corporation",
					"warehouse": "RMFS - Guyong",
					"date_start": "2026-07-20",
					"date_end": "2026-07-26",
					"preparation_date": "2026-07-20",
					"workflow_state": "Draft",
					"schedule_details": [row],
				}
			).insert(ignore_permissions=True)

			self.assertTrue(schedule.name.startswith("PEAS-"))
			self.assertEqual(schedule.schedule_details[0].production_plantilla, plantilla.name)
		finally:
			frappe.db.rollback(save_point=savepoint)
