from unittest import TestCase
from unittest.mock import patch

from frappe import _dict

from qcmc_logic.api.job_card_time_log import _validate_operation_output_limits


def job_card(name, operation_id, good=0, rejected=0):
	return _dict(
		name=name,
		work_order="WO-1",
		operation_id=operation_id,
		total_completed_qty=0,
		time_logs=[
			_dict(qcmc_good_qty=good, qcmc_rejected_qty=rejected, qcmc_output_revision=1),
		],
		precision=lambda field: 2,
	)


def make_work_order(operations, quantity=100):
	return _dict(
		name="WO-1",
		qty=quantity,
		docstatus=1,
		status="In Process",
		operations=operations,
		check_permission=lambda permission: None,
	)


class TestProcessCardOutputLimits(TestCase):
	def setUp(self):
		self.operations = [
			_dict(name="WO-OP-1", sequence_id=1, idx=1),
			_dict(name="WO-OP-2", sequence_id=2, idx=2),
		]

	def test_downstream_output_is_limited_by_upstream_good_quantity_only(self):
		current = job_card("JC-DOWNSTREAM", "WO-OP-2", good=20, rejected=5)
		upstream = job_card("JC-UPSTREAM", "WO-OP-1", good=20, rejected=30)
		with patch("qcmc_logic.api.job_card_time_log.frappe") as frappe:
			frappe.get_doc.side_effect = [
				make_work_order(self.operations),
				upstream,
			]
			frappe.get_list.side_effect = [
				[_dict(name=current.name)],
				[_dict(name=upstream.name)],
			]
			frappe.db.count.side_effect = [1, 1]
			_validate_operation_output_limits(current)

	def test_downstream_output_cannot_exceed_upstream_accepted_output(self):
		current = job_card("JC-DOWNSTREAM", "WO-OP-2", good=21, rejected=5)
		upstream = job_card("JC-UPSTREAM", "WO-OP-1", good=20, rejected=30)
		with patch("qcmc_logic.api.job_card_time_log.frappe") as frappe:
			frappe.get_doc.side_effect = [
				make_work_order(self.operations),
				upstream,
			]
			frappe.get_list.side_effect = [
				[_dict(name=current.name)],
				[_dict(name=upstream.name)],
			]
			frappe.db.count.side_effect = [1, 1]
			frappe.throw.side_effect = lambda message, *args, **kwargs: (_ for _ in ()).throw(ValueError(message))
			with self.assertRaisesRegex(ValueError, "accepted quantity"):
				_validate_operation_output_limits(current)

	def test_first_operation_cannot_exceed_work_order_quantity(self):
		current = job_card("JC-FIRST", "WO-OP-1", good=100, rejected=1)
		work_order = make_work_order(self.operations[:1])
		work_order.qty = 100
		with patch("qcmc_logic.api.job_card_time_log.frappe") as frappe:
			frappe.get_doc.return_value = work_order
			frappe.get_list.return_value = [_dict(name=current.name)]
			frappe.db.count.return_value = 1
			frappe.throw.side_effect = lambda message, *args, **kwargs: (_ for _ in ()).throw(ValueError(message))
			with self.assertRaisesRegex(ValueError, "Work Order quantity"):
				_validate_operation_output_limits(current)

