from unittest import TestCase
from unittest.mock import patch

from frappe import _dict

from qcmc_logic.customs.job_card import sync_non_final_operation_progress


def operation(name, sequence_id, idx):
	return _dict(name=name, sequence_id=sequence_id, idx=idx)


def job_card(operation_id):
	return _dict(
		name="JC-TEST",
		work_order="WO-TEST",
		operation_id=operation_id,
		is_corrective_job_card=0,
	)


class TestDraftJobCardProgress(TestCase):
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

	def test_final_operation_is_not_updated_from_draft_actual_time(self):
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

			sync_non_final_operation_progress(job_card(packing.name))

		frappe.get_all.assert_not_called()
		frappe.db.set_value.assert_not_called()
