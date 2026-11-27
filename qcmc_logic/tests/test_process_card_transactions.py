from datetime import datetime
from unittest import TestCase
from unittest.mock import patch

from frappe import _dict

from qcmc_logic.api.process_card_services import _subtract_intervals, _union_seconds
from qcmc_logic.customs import process_card_transactions as transactions
from qcmc_logic.customs.process_card_transactions import _validate_participation_overlaps


def dt(value):
	return datetime.fromisoformat(value)


class TestProcessCardMachineMetrics(TestCase):
	def test_overlapping_downtime_intervals_are_counted_once(self):
		intervals = [
			(dt("2026-11-10T08:00:00"), dt("2026-11-10T10:00:00")),
			(dt("2026-11-10T09:30:00"), dt("2026-11-10T11:00:00")),
		]

		self.assertEqual(_union_seconds(intervals), 3 * 60 * 60)

	def test_actual_run_subtracts_downtime_overlap_from_output_interval_union(self):
		output = [(dt("2026-11-10T06:00:00"), dt("2026-11-10T10:00:00"))]
		downtime = [(dt("2026-11-10T08:00:00"), dt("2026-11-10T09:00:00"))]

		self.assertEqual(_union_seconds(_subtract_intervals(output, downtime)), 3 * 60 * 60)

	def test_overlapping_job_card_output_intervals_do_not_double_machine_run_time(self):
		output = [
			(dt("2026-11-10T06:00:00"), dt("2026-11-10T08:00:00")),
			(dt("2026-11-10T07:00:00"), dt("2026-11-10T09:00:00")),
		]

		self.assertEqual(_union_seconds(output), 3 * 60 * 60)


class TestProcessCardParticipationTransfers(TestCase):
	def setUp(self):
		self.card = _dict(
			name="PC-1",
			shift_end="2026-11-10 18:00:00",
			jobs=[_dict(job_card="JC-1")],
		)

	def test_adjacent_employee_intervals_allow_transfer(self):
		doc = _dict(
			name="JC-1",
			time_logs=[
				_dict(qcmc_process_card="PC-1", employee="EMP-1", from_time="2026-11-10 06:00:00", to_time="2026-11-10 10:00:00"),
				_dict(qcmc_process_card="PC-1", employee="EMP-1", from_time="2026-11-10 10:00:00", to_time="2026-11-10 18:00:00"),
			],
		)

		_validate_participation_overlaps(doc, {"PC-1": self.card})

	def test_overlapping_employee_intervals_are_rejected(self):
		doc = _dict(
			name="JC-1",
			time_logs=[
				_dict(qcmc_process_card="PC-1", employee="EMP-1", from_time="2026-11-10 06:00:00", to_time="2026-11-10 11:00:00"),
				_dict(qcmc_process_card="PC-1", employee="EMP-1", from_time="2026-11-10 10:00:00", to_time="2026-11-10 18:00:00"),
			],
		)
		with patch.object(transactions, "_", side_effect=lambda value: value), patch("qcmc_logic.customs.process_card_transactions.frappe") as frappe:
			frappe.throw.side_effect = ValueError("overlap")
			with self.assertRaisesRegex(ValueError, "overlap"):
				_validate_participation_overlaps(doc, {"PC-1": self.card})


class TestParticipationStatusLock(TestCase):
	def _make_doc(self, current, previous):
		return _dict(
			name="JC-1",
			company="Company A",
			workstation="WS-1",
			time_logs=[current] if current else [],
			get_doc_before_save=lambda: _dict(time_logs=[previous] if previous else []),
		)

	def test_unchanged_participation_remains_readable_after_approval(self):
		row = _dict(
			name="TL-1",
			qcmc_process_card="PC-1",
			employee="EMP-1",
			from_time="2026-11-10 06:00:00",
			to_time="2026-11-10 18:00:00",
			qcmc_pay_mode="DR",
			qcmc_mca_approval_reference=None,
		)
		card = _dict(
			name="PC-1",
			status="Approved",
			company="Company A",
			workstation="WS-1",
			shift_start="2026-11-10 06:00:00",
			shift_end="2026-11-10 18:00:00",
			jobs=[_dict(job_card="JC-1")],
		)
		doc = self._make_doc(row, row)
		with patch.object(transactions, "_process_card", return_value=card), patch.object(transactions, "frappe"), patch.object(
			transactions, "_", side_effect=lambda value: value,
		):
			transactions.validate_job_card_participation(doc)

	def test_participation_cannot_be_changed_after_approval(self):
		previous = _dict(
			name="TL-1",
			qcmc_process_card="PC-1",
			employee="EMP-1",
			from_time="2026-11-10 06:00:00",
			to_time="2026-11-10 18:00:00",
			qcmc_pay_mode="DR",
			qcmc_mca_approval_reference=None,
		)
		current = _dict({**previous, "to_time": "2026-11-10 17:00:00"})
		card = _dict(name="PC-1", status="Approved")
		doc = self._make_doc(current, previous)
		with patch.object(transactions, "_process_card", return_value=card), patch.object(
			transactions, "_", side_effect=lambda value: value,
		), patch.object(transactions, "frappe") as frappe:
			frappe.throw.side_effect = lambda message, *args, **kwargs: (_ for _ in ()).throw(ValueError(message))
			with self.assertRaisesRegex(ValueError, "cannot be added or changed"):
				transactions.validate_job_card_participation(doc)
			removed = self._make_doc(None, previous)
			with self.assertRaisesRegex(ValueError, "cannot be removed or changed"):
				transactions.validate_job_card_participation(removed)


class TestQualityInspectionRejections(TestCase):
	def setUp(self):
		self.card = _dict(name="PC-1", company="Company A")
		self.job = _dict(name="JC-1", production_item="ITEM-1", time_logs=[
			_dict(
				name="TL-1",
				qcmc_process_card="PC-1",
				qcmc_output_revision=1,
				qcmc_good_qty=2,
				qcmc_rejected_qty=1,
			),
		])

	def inspection(self, output_time_log=None, rejected_qty=1):
		return _dict(
			name="QI-1",
			qcmc_process_card="PC-1",
			qcmc_output_time_log=output_time_log,
			reference_type="Job Card",
			reference_name="JC-1",
			item_code="ITEM-1",
			company="Company A",
			inspection_type="In Process",
			readings=[_dict(
				idx=1,
				status="Rejected",
				qcmc_rejected_qty=rejected_qty,
				qcmc_reject_reason="Surface defect",
			)],
		)

	def validate(self, doc):
		with (
			patch.object(transactions, "_", side_effect=lambda value: value),
			patch.object(transactions, "_process_card", return_value=self.card),
			patch.object(transactions, "_linked_job_card", return_value=self.job),
			patch.object(transactions, "frappe") as frappe,
		):
			frappe.get_list.return_value = []
			frappe.db.sql.return_value = []
			frappe.throw.side_effect = lambda message, *args, **kwargs: (_ for _ in ()).throw(ValueError(message))
			transactions.validate_quality_inspection(doc)

	def test_qa_rejection_requires_a_linked_production_interval(self):
		with self.assertRaisesRegex(ValueError, "must reference a production output interval"):
			self.validate(self.inspection())

	def test_qa_rejection_cannot_exceed_linked_output_quantity(self):
		with self.assertRaisesRegex(ValueError, "cannot exceed the linked production output quantity"):
			self.validate(self.inspection("TL-1", rejected_qty=4))

