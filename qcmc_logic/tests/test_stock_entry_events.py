from unittest import TestCase
from unittest.mock import patch

from frappe import _dict

from qcmc_logic.customs.stock_entry import (
	update_final_job_card_time_log_on_cancel,
	update_final_job_card_time_log_on_submit,
)


def manufacture_entry(qty):
	return _dict(
		purpose="Manufacture",
		fg_completed_qty=qty,
		custom_final_job_card="JC-TEST",
		custom_job_card_time_log="TIME-TEST",
	)


class TestStockEntryJobCardTimeLog(TestCase):
	def test_submit_recalculates_job_card_manufactured_qty(self):
		doc = manufacture_entry(25)

		with patch("qcmc_logic.customs.stock_entry.frappe") as frappe:
			job_card = frappe.get_doc.return_value
			frappe.get_all.side_effect = [
				["STE-1"],
				[_dict(qty=25)],
			]
			update_final_job_card_time_log_on_submit(doc)

		frappe.get_doc.assert_called_once_with("Job Card", "JC-TEST")
		job_card.db_set.assert_called_once_with("manufactured_qty", 25)
		self.assertEqual(job_card.manufactured_qty, 25)
		job_card.set_status.assert_called_once_with(update_status=True)
		frappe.db.set_value.assert_not_called()

	def test_cancel_recalculates_job_card_manufactured_qty(self):
		doc = manufacture_entry(25)

		with patch("qcmc_logic.customs.stock_entry.frappe") as frappe:
			job_card = frappe.get_doc.return_value
			frappe.get_all.side_effect = [
				["STE-1"],
				[_dict(qty=10)],
			]
			update_final_job_card_time_log_on_cancel(doc)

		frappe.get_doc.assert_called_once_with("Job Card", "JC-TEST")
		job_card.db_set.assert_called_once_with("manufactured_qty", 10)
		self.assertEqual(job_card.manufactured_qty, 10)
		job_card.set_status.assert_called_once_with(update_status=True)
		frappe.db.set_value.assert_not_called()

	def test_non_manufacture_entry_is_ignored(self):
		doc = manufacture_entry(25)
		doc.purpose = "Material Transfer for Manufacture"

		with patch("qcmc_logic.customs.stock_entry.frappe") as frappe:
			update_final_job_card_time_log_on_submit(doc)

		frappe.db.get_value.assert_not_called()
