from unittest import TestCase
from unittest.mock import patch

from frappe import _dict

from qcmc_logic.customs.stock_entry import (
	set_manufacture_actual_weight_uom,
	set_stock_entry_warehouse_code,
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

		with (
			patch("qcmc_logic.customs.stock_entry.frappe") as frappe,
			patch("qcmc_logic.customs.stock_entry._", side_effect=lambda message: message),
		):
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


class TestStockEntryWarehouseCode(TestCase):
	def test_material_receipt_uses_target_warehouse_code(self):
		doc = _dict(
			purpose="Material Receipt",
			custom_msrp_no="MSRP-TEST",
			custom_final_process="PROCESS-FINAL",
			custom_daily_job_report="DJR-FINAL",
			to_warehouse=None,
			custom_wh_code=None,
			items=[_dict(t_warehouse="Stockroom - Sta Clara")],
		)

		with (
			patch("qcmc_logic.customs.stock_entry.frappe") as frappe,
			patch("qcmc_logic.customs.stock_entry._", side_effect=lambda message: message),
		):
			frappe.db.get_value.side_effect = [
				_dict(msjr_no="MSJR-TEST", workflow_state="Completed"),
				_dict(parent="MSRP-TEST", process_name="FINAL INSPECTION", status="Completed"),
				_dict(project_no="MSRP-TEST", process_no="PROCESS-FINAL"),
				"QC-SC-STK",
			]
			set_msjr_receipt_warehouse_code(doc)

		self.assertEqual(doc.custom_wh_code, "QC-SC-STK")
		frappe.db.get_value.assert_called_with(
			"Warehouse", "Stockroom - Sta Clara", "custom_wh_code"
		)

	def test_material_issue_uses_source_warehouse_code(self):
		doc = _dict(
			purpose="Material Issue",
			from_warehouse=None,
			custom_wh_code=None,
			items=[_dict(s_warehouse="RMFS - Sta Clara")],
		)

		with patch("qcmc_logic.customs.stock_entry.frappe") as frappe:
			frappe.db.get_value.return_value = "QC-SC-RM"
			set_stock_entry_warehouse_code(doc)

		self.assertEqual(doc.custom_wh_code, "QC-SC-RM")
		frappe.db.get_value.assert_called_once_with(
			"Warehouse", "RMFS - Sta Clara", "custom_wh_code"
		)

	def test_multiple_target_warehouses_are_rejected(self):
		doc = _dict(
			purpose="Material Receipt",
			to_warehouse=None,
			items=[
				_dict(t_warehouse="Warehouse A"),
				_dict(t_warehouse="Warehouse B"),
			],
		)

		with (
			patch("qcmc_logic.customs.stock_entry.frappe") as frappe,
			patch("qcmc_logic.customs.stock_entry._", side_effect=lambda message: message),
		):
			frappe.throw.side_effect = RuntimeError
			with self.assertRaises(RuntimeError):
				set_stock_entry_warehouse_code(doc)


class TestManufactureActualWeightUOM(TestCase):
	def test_sets_default_weight_uom_on_finished_item_rows(self):
		doc = _dict(
			purpose="Manufacture",
			stock_entry_type="Manufacture",
			items=[
				_dict(is_finished_item=1, custom_actual_weight_uom=None),
				_dict(is_finished_item=0, custom_actual_weight_uom=None),
			],
		)

		with patch("qcmc_logic.customs.stock_entry.frappe") as frappe:
			frappe.db.get_single_value.return_value = "Kg"
			set_manufacture_actual_weight_uom(doc)

		self.assertEqual(doc["items"][0].custom_actual_weight_uom, "Kg")
		self.assertIsNone(doc["items"][1].custom_actual_weight_uom)
		frappe.db.get_single_value.assert_called_once_with(
			"Stock Settings", "custom_default_actual_weight_uom"
		)

	def test_keeps_existing_finished_item_weight_uom(self):
		doc = _dict(
			purpose="Manufacture",
			stock_entry_type="Manufacture",
			items=[_dict(is_finished_item=1, custom_actual_weight_uom="g")],
		)

		with patch("qcmc_logic.customs.stock_entry.frappe") as frappe:
			frappe.db.get_single_value.return_value = "Kg"
			set_manufacture_actual_weight_uom(doc)

		self.assertEqual(doc["items"][0].custom_actual_weight_uom, "g")

	def test_non_manufacture_entry_is_ignored(self):
		doc = _dict(
			purpose="Material Transfer",
			stock_entry_type="Material Transfer",
			items=[_dict(is_finished_item=1, custom_actual_weight_uom=None)],
		)

		with patch("qcmc_logic.customs.stock_entry.frappe") as frappe:
			set_manufacture_actual_weight_uom(doc)

		self.assertIsNone(doc["items"][0].custom_actual_weight_uom)
		frappe.db.get_single_value.assert_not_called()
