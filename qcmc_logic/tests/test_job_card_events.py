from unittest import TestCase
from unittest.mock import patch

from frappe import _dict

from erpnext.manufacturing.doctype.work_order.work_order import split_qty_based_on_batch_size
from qcmc_logic.customs.job_card import sync_non_final_operation_progress


def operation(name, sequence_id, idx):
	return _dict(name=name, sequence_id=sequence_id, idx=idx)


def job_card(operation_id, **kwargs):
	return _dict(
		name="JC-TEST",
		work_order="WO-TEST",
		operation_id=operation_id,
		is_corrective_job_card=0,
		total_completed_qty=kwargs.pop("total_completed_qty", 0),
		time_logs=kwargs.pop("time_logs", []),
		flags=kwargs.pop("flags", _dict()),
		**kwargs,
	)


class TestDraftJobCardProgress(TestCase):
	def test_initial_empty_job_card_insert_skips_progress_sync(self):
		doc = job_card("WO-OP-1", flags=_dict(in_insert=True))

		with patch("qcmc_logic.customs.job_card.frappe") as frappe:
			sync_non_final_operation_progress(doc, "on_update")

		frappe.get_doc.assert_not_called()
		frappe.get_all.assert_not_called()
		frappe.db.set_value.assert_not_called()

	def test_non_final_draft_progress_updates_work_order_operation(self):
		injection = operation("WO-OP-1", 1, 1)
		packing = operation("WO-OP-2", 2, 2)
		work_order = _dict(
			name="WO-TEST",
			docstatus=1,
			status="Not Started",
			qty=100,
			operations=[injection, packing],
		)

		with patch("qcmc_logic.customs.job_card.frappe") as frappe:
			frappe.get_doc.return_value = work_order
			frappe.get_all.return_value = [
				_dict(
					docstatus=0,
					total_completed_qty=30,
					process_loss_qty=70,
				),
				_dict(
					docstatus=1,
					total_completed_qty=20,
					process_loss_qty=5,
				),
			]

			sync_non_final_operation_progress(job_card(injection.name))

		frappe.db.set_value.assert_any_call(
			"Work Order Operation",
			injection.name,
			{
				"completed_qty": 50,
				"process_loss_qty": 0,
				"status": "Work in Progress",
			},
			update_modified=False,
		)
		frappe.db.set_value.assert_any_call(
			"Work Order",
			work_order.name,
			"status",
			"In Process",
			update_modified=False,
		)

	def test_final_operation_partial_shift_is_not_treated_as_process_loss(self):
		injection = operation("WO-OP-1", 1, 1)
		packing = operation("WO-OP-2", 2, 2)
		work_order = _dict(
			name="WO-TEST",
			docstatus=1,
			status="In Process",
			qty=100,
			operations=[injection, packing],
		)

		with patch("qcmc_logic.customs.job_card.frappe") as frappe:
			frappe.get_doc.return_value = work_order
			frappe.get_all.return_value = [
				_dict(total_completed_qty=25),
			]

			sync_non_final_operation_progress(
				job_card(packing.name, total_completed_qty=25, process_loss_qty=75)
			)

		frappe.db.set_value.assert_any_call(
			"Job Card", "JC-TEST", "process_loss_qty", 0, update_modified=False
		)
		frappe.db.set_value.assert_any_call(
			"Work Order Operation",
			packing.name,
			{
				"completed_qty": 25,
				"process_loss_qty": 0,
				"status": "Work in Progress",
			},
			update_modified=False,
		)

	def test_cancel_with_zero_remaining_progress_resets_operation(self):
		injection = operation("WO-OP-1", 1, 1)
		packing = operation("WO-OP-2", 2, 2)
		work_order = _dict(
			name="WO-TEST",
			docstatus=1,
			status="In Process",
			qty=100,
			operations=[injection, packing],
		)

		with patch("qcmc_logic.customs.job_card.frappe") as frappe:
			frappe.get_doc.return_value = work_order
			frappe.get_all.return_value = []

			sync_non_final_operation_progress(job_card(injection.name), "on_cancel")

		frappe.db.set_value.assert_called_once_with(
			"Work Order Operation",
			injection.name,
			{
				"completed_qty": 0,
				"process_loss_qty": 0,
				"status": "Pending",
			},
			update_modified=False,
		)


class TestJobCardBatchSize(TestCase):
	def test_batch_size_one_creates_one_iteration_per_unit(self):
		work_order = _dict(qty=10, has_serial_no=0)
		row = _dict(operation="FORMING", batch_size=1)
		remaining_qty = work_order.qty
		job_card_quantities = []

		with patch(
			"erpnext.manufacturing.doctype.work_order.work_order.frappe.db.get_value",
			return_value=1,
		):
			while remaining_qty > 0:
				remaining_qty = split_qty_based_on_batch_size(work_order, row, remaining_qty)
				job_card_quantities.append(row.job_card_qty)

		self.assertEqual(job_card_quantities, [1] * 10)
