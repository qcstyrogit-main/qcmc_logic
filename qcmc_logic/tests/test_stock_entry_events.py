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
	def test_submit_adds_manufactured_qty_to_actual_time(self):
		doc = manufacture_entry(25)

		with (
			patch("qcmc_logic.customs.stock_entry.frappe") as frappe,
			patch("qcmc_logic.customs.stock_entry._update_job_card_completed_qty") as update_total,
		):
			frappe.db.get_value.return_value = 10
			update_final_job_card_time_log_on_submit(doc)

		frappe.db.set_value.assert_called_once_with(
			"Job Card Time Log",
			"TIME-TEST",
			"completed_qty",
			35,
			update_modified=False,
		)
		update_total.assert_called_once_with("JC-TEST")

	def test_cancel_reverses_manufactured_qty_from_actual_time(self):
		doc = manufacture_entry(25)

		with (
			patch("qcmc_logic.customs.stock_entry.frappe") as frappe,
			patch("qcmc_logic.customs.stock_entry._update_job_card_completed_qty") as update_total,
		):
			frappe.db.get_value.return_value = 40
			update_final_job_card_time_log_on_cancel(doc)

		frappe.db.set_value.assert_called_once_with(
			"Job Card Time Log",
			"TIME-TEST",
			"completed_qty",
			15,
			update_modified=False,
		)
		update_total.assert_called_once_with("JC-TEST")

	def test_non_manufacture_entry_is_ignored(self):
		doc = manufacture_entry(25)
		doc.purpose = "Material Transfer for Manufacture"

		with patch("qcmc_logic.customs.stock_entry.frappe") as frappe:
			update_final_job_card_time_log_on_submit(doc)

		frappe.db.get_value.assert_not_called()
