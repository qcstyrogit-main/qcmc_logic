import unittest
from unittest.mock import patch

from qcmc_logic.qcmc_logics.doctype.weekly_production_plan.weekly_production_plan import (
	get_possible_sales_order_items,
	make_record_no,
)


class TestWeeklyProductionPlan(unittest.TestCase):
	def test_record_number_uses_section_and_start_date(self):
		self.assertEqual(make_record_no("CPS", "2026-10-19"), "CPS101926")

	def test_record_number_normalizes_section(self):
		self.assertEqual(make_record_no("Plant Floor 1", "2026-01-02"), "PLANTFLOOR1010226")

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
