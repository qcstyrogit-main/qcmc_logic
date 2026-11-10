import unittest
from types import SimpleNamespace
from unittest.mock import patch

from qcmc_logic.qcmc_logics.doctype.weekly_production_plan.weekly_production_plan import (
	build_schedule_hour_totals,
	calculate_extrusion_values,
	calculate_secondary_values,
	extract_production_rows,
	get_item_production_details,
	get_possible_sales_order_items,
	is_extrusion_section,
	make_record_no,
	sync_secondary_values,
	validate_slot_paid_hours,
	validate_start_date,
)


class TestWeeklyProductionPlan(unittest.TestCase):
	def test_extract_production_rows_finds_headers_and_aggregates_products(self):
		class Worksheet:
			rows = [
				("Monthly plan", None, None),
				("Product Code", "Description", "For Production (October) Oct+TIL - SOH"),
				("ITEM-1", "First", "1,200"),
				("ITEM-2", "Second", "-"),
				("ITEM-1", "First", 300),
			]

			def iter_rows(self, min_row=1, values_only=False):
				return iter(self.rows[min_row - 1:])

		self.assertEqual(
			extract_production_rows(Worksheet()),
			[{"product_code": "ITEM-1", "for_production_qty": 1500.0, "excel_rows": [3, 5]}],
		)

	def test_record_number_uses_section_and_start_date(self):
		self.assertEqual(make_record_no("CPS", "2026-10-19"), "CPS101926")

	def test_record_number_normalizes_section(self):
		self.assertEqual(make_record_no("Plant Floor 1", "2026-01-02"), "PLANTFLOOR1010226")

	@patch("qcmc_logic.qcmc_logics.doctype.weekly_production_plan.weekly_production_plan.frappe")
	def test_start_date_accepts_monday(self, frappe):
		validate_start_date("2026-10-19")
		frappe.throw.assert_not_called()

	@patch("qcmc_logic.qcmc_logics.doctype.weekly_production_plan.weekly_production_plan.frappe")
	def test_start_date_rejects_non_monday(self, frappe):
		with patch(
			"qcmc_logic.qcmc_logics.doctype.weekly_production_plan.weekly_production_plan._",
			side_effect=lambda message: message,
		):
			validate_start_date("2026-10-21")
		frappe.throw.assert_called_once_with("Start Date must be a Monday.")

	def test_extrusion_section_matching_is_case_insensitive(self):
		self.assertTrue(is_extrusion_section(" extrusion "))
		self.assertTrue(is_extrusion_section("EXTRUSION35"))
		self.assertTrue(is_extrusion_section(" extrusion99 "))
		self.assertFalse(is_extrusion_section("CPS"))

	@patch("qcmc_logic.qcmc_logics.doctype.weekly_production_plan.weekly_production_plan.frappe")
	def test_slot_paid_hours_accepts_a_total_of_24(self, frappe):
		rows = [
			SimpleNamespace(machine="AVM1", plan_date="2026-10-05", idx=1, get=lambda _field: 12),
			SimpleNamespace(machine="AVM1", plan_date="2026-10-05", idx=2, get=lambda _field: 12),
		]
		validate_slot_paid_hours(rows, "paid_hrs", "FG 1")
		frappe.throw.assert_not_called()

	@patch("qcmc_logic.qcmc_logics.doctype.weekly_production_plan.weekly_production_plan.frappe")
	def test_slot_paid_hours_rejects_a_total_above_24(self, frappe):
		frappe.throw.side_effect = RuntimeError("paid hours exceeded")
		rows = [
			SimpleNamespace(machine="AVM1", plan_date="2026-10-05", idx=1, get=lambda _field: 12),
			SimpleNamespace(machine="AVM1", plan_date="2026-10-05", idx=2, get=lambda _field: 13),
		]
		with patch(
			"qcmc_logic.qcmc_logics.doctype.weekly_production_plan.weekly_production_plan._",
			side_effect=lambda message: message,
		):
			with self.assertRaisesRegex(RuntimeError, "paid hours exceeded"):
				validate_slot_paid_hours(rows, "paid_hrs", "FG 1")

	def test_extrusion_output_formulas(self):
		self.assertEqual(
			calculate_extrusion_values(24, 1, 2, 3, 100, 20),
			{
				"plan_hours": 18,
				"number_of_kgs": 1800,
				"number_of_rolls": 90,
			},
		)

	def test_extrusion_rolls_are_zero_when_standard_weight_is_zero(self):
		values = calculate_extrusion_values(24, 1, 2, 3, 100, 0)
		self.assertEqual(values["plan_hours"], 18)
		self.assertEqual(values["number_of_kgs"], 1800)
		self.assertEqual(values["number_of_rolls"], 0)

	def test_extrusion_rolls_discard_the_decimal_portion(self):
		self.assertEqual(calculate_extrusion_values(13, 0, 0, 0, 100, 300)["number_of_rolls"], 4)
		self.assertEqual(calculate_extrusion_values(13.5, 0, 0, 0, 100, 300)["number_of_rolls"], 4)

	@patch("qcmc_logic.qcmc_logics.doctype.weekly_production_plan.weekly_production_plan.frappe")
	def test_extrusion_standard_weight_uses_bom_standard_pack(self, frappe):
		frappe.db.sql.return_value = [
			SimpleNamespace(
				name="BOM-ROLL-001",
				cavs=1,
				soph=100,
				cycle_time=1,
				trim_percent=5,
				standard_pack=361.75,
			)
		]
		frappe.db.get_value.return_value = {
			"item_name": "Roll Item",
			"description": "Roll Item",
			"weight_per_unit": 20,
		}

		details = get_item_production_details("ROLL-001", "EXT-01", check_permission=False)

		self.assertEqual(details["roll_standard_weight_gm"], 361.75)
		self.assertIn("bom.custom_standard_pack as standard_pack", frappe.db.sql.call_args.args[0])

	def test_machine_schedule_hour_totals_for_fg_items(self):
		rows = [
			SimpleNamespace(
				machine="AVM1", plan_date="2026-10-05", paid_hrs=16,
				vos=2, cm_co=1, stab=0.5,
			),
			SimpleNamespace(
				machine="AVM1", plan_date="2026-10-05", paid_hrs=8,
				vos=1, cm_co=0.5, stab=0.25,
			),
		]
		values = next(iter(build_schedule_hour_totals(rows).values()))
		self.assertEqual(values["total_paid_time_hrs"], 24)
		self.assertEqual(values["total_planned_vos_hrs"], 3)
		self.assertEqual(values["total_cm_co_hrs"], 1.5)
		self.assertEqual(values["total_stabilization_hrs"], 0.75)
		self.assertEqual(values["remaining_paid_hrs"], 0)

	def test_secondary_output_uses_parent_quantity_and_factor_rate(self):
		self.assertEqual(
			calculate_secondary_values(1225, 100, 42.345),
			{"daily_volume_qty": 1225, "daily_volume_kgs": 51.872625},
		)
		self.assertEqual(
			calculate_secondary_values(1225, 50, 42.345),
			{"daily_volume_qty": 612.5, "daily_volume_kgs": 25.9363125},
		)

	def test_secondary_inherits_factor_rate_and_cycle_time_from_fg1(self):
		parent = SimpleNamespace(f_rate=75, cycle_time=2.5, daily_volume_qty=1200)
		secondary = SimpleNamespace(factor_rate=100, cycle_time=1, std_weight_gm=40)
		secondary.update = lambda values: secondary.__dict__.update(values)

		sync_secondary_values(secondary, parent)

		self.assertEqual(secondary.factor_rate, 75)
		self.assertEqual(secondary.cycle_time, 2.5)
		self.assertEqual(secondary.daily_volume_qty, 900)
		self.assertEqual(secondary.daily_volume_kgs, 36)

	@patch("qcmc_logic.qcmc_logics.doctype.weekly_production_plan.weekly_production_plan.frappe")
	def test_possible_sales_orders_are_filtered_by_machine_bom_and_delivery_note(self, frappe):
		frappe.has_permission.return_value = True
		frappe.db.sql.return_value = []

		self.assertEqual(get_possible_sales_order_items("MACHINE-1"), [])

		query = frappe.db.sql.call_args.args[0]
		self.assertIn("bom.custom_machine = %(machine)s", query)
		self.assertIn("operation.workstation = %(machine)s", query)
		self.assertIn("so.docstatus < 2", query)
		self.assertIn("so.docstatus = 0 or so.status in ('To Deliver and Bill', 'To Deliver')", query)
		self.assertIn("coalesce(soi.delivered_qty, 0) < soi.qty", query)
		self.assertEqual(frappe.db.sql.call_args.args[1], {"machine": "MACHINE-1"})
		self.assertTrue(frappe.db.sql.call_args.kwargs["as_dict"])

	@patch("qcmc_logic.qcmc_logics.doctype.weekly_production_plan.weekly_production_plan.frappe")
	def test_blank_machine_returns_no_candidates_without_querying(self, frappe):
		frappe.has_permission.return_value = True
		self.assertEqual(get_possible_sales_order_items(""), [])
		frappe.db.sql.assert_not_called()
