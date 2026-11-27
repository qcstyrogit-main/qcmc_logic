from unittest import TestCase
from unittest.mock import patch

from frappe import _dict

from qcmc_logic.overrides.job_card import CustomJobCard


def make_job_card(qty):
	doc = object.__new__(CustomJobCard)
	doc.__dict__.update(
		name="JC-NEW",
		work_order="WO-TEST",
		operation_id="WO-OP-1",
		operation="REPACKING",
		for_quantity=qty,
		total_completed_qty=0,
	)
	return doc


class TestJobCardEmployeeSummary(TestCase):
	def test_output_only_row_does_not_create_blank_summary_employee(self):
		doc = make_job_card(5000)
		output = _dict(qcmc_output_revision=1, qcmc_good_qty=2000)
		participation = _dict(employee="EMP-1", qcmc_output_revision=0)
		blank = _dict(employee=None)
		real = _dict(employee="EMP-1")
		doc.__dict__.update(time_logs=[output, participation], employee=[blank, real])
		doc.__dict__["remove"] = lambda row: doc.employee.remove(row)
		doc._remove_blank_summary_employees()
		self.assertEqual(doc.employee, [real])
		self.assertEqual(doc.time_logs, [output, participation])


class TestShiftJobCardQuantityValidation(TestCase):
	@patch("qcmc_logic.overrides.job_card.frappe")
	def test_partial_submitted_shifts_leave_actual_remainder_available(self, frappe):
		frappe.get_cached_value.return_value = 50000
		frappe.db.get_single_value.return_value = 0
		frappe.db.get_value.return_value = 35000
		frappe.get_all.return_value = []

		make_job_card(15000).validate_job_card_qty()

		frappe.throw.assert_not_called()

	@patch("qcmc_logic.overrides.job_card.frappe")
	def test_current_cards_completed_quantity_is_not_counted_twice(self, frappe):
		frappe.get_cached_value.return_value = 50000
		frappe.db.get_single_value.return_value = 0
		frappe.db.get_value.return_value = 50000
		frappe.get_all.return_value = []
		doc = make_job_card(15000)
		doc.total_completed_qty = 15000

		doc.validate_job_card_qty()

		frappe.throw.assert_not_called()

	@patch("qcmc_logic.overrides.job_card.frappe")
	def test_open_draft_commitments_prevent_overproduction(self, frappe):
		frappe.get_cached_value.return_value = 50000
		frappe.db.get_single_value.return_value = 0
		frappe.db.get_value.return_value = 35000
		frappe.get_all.return_value = [_dict(for_quantity=10000, total_completed_qty=0)]

		make_job_card(15000).validate_job_card_qty()

		frappe.throw.assert_called_once()
