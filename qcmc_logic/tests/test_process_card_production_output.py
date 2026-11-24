import json
from datetime import datetime
from unittest import TestCase
from unittest.mock import Mock, patch

from frappe import _dict

from qcmc_logic.api import job_card_time_log as output_api
from qcmc_logic.api import process_card_workbench as workbench_api


def fake_job(rows=None):
	job = _dict(
		name="JC-1", company="Company A", workstation="WS-1", work_order="WO-1",
		operation_id="WO-OP-1", production_item="ITEM-1", for_quantity=100,
		total_completed_qty=20, docstatus=0, status="Open", sub_operations=[],
		time_logs=list(rows or []), precision=lambda field: 2, flags=_dict(),
	)
	job.append = lambda table, values: _append(job, values)
	job.save = lambda: None
	return job


def _append(job, values):
	row = _dict(name=f"TL-{len(job.time_logs) + 1}", idx=len(job.time_logs) + 1, **values)
	job.time_logs.append(row)
	return row


def fake_card(status="In Progress"):
	return _dict(
		name="PC-1", status=status, company="Company A", workstation="WS-1",
		shift_start="2026-11-10 06:00:00", shift_end="2026-11-10 18:00:00",
		jobs=[_dict(job_card="JC-1")],
	)


class TestCheckpointSchedule(TestCase):
	def test_packing_operation_soph_and_output_item_override_precede_item_metadata(self):
		job = fake_job()
		job.operation = "Packing"
		job.operation_id = "WO-OP-1"
		job.production_item = "BASE-ITEM"
		operation = _dict(custom_pack_soph=1200, custom_soph=900, custom_eps_output_item="PACK-ITEM")
		with patch.object(workbench_api, "frappe", _dict(
			db=_dict(exists=Mock(return_value=True)), get_doc=Mock(return_value=operation),
			get_list=Mock(return_value=[_dict(custom_number_of_color=3)]),
		)):
			standards = workbench_api._job_output_standards(job)
		self.assertEqual(standards, {"soph": 1200, "color_count": 3, "output_item": "PACK-ITEM"})

	def test_operation_soph_falls_back_to_bom_custom_soph(self):
		job = fake_job()
		job.operation = "Cut"
		job.operation_id = "WO-OP-1"
		operation = _dict(custom_pack_soph=0, custom_soph=0, custom_eps_output_item=None)
		bom = _dict(custom_pack_soph=0, custom_soph=750, check_permission=Mock())
		fake_frappe = _dict(
			db=_dict(exists=Mock(return_value=True), get_value=Mock(side_effect=["BOM-1", 750])),
			get_doc=Mock(side_effect=[operation, bom]), get_list=Mock(return_value=[]), PermissionError=PermissionError,
		)
		with patch.object(workbench_api, "frappe", fake_frappe):
			standards = workbench_api._job_output_standards(job)
		self.assertEqual(standards["soph"], 750)
		self.assertEqual(standards["output_item"], "ITEM-1")

	def test_default_twelve_hour_shift_generates_six_two_hour_checkpoints(self):
		card = fake_card()
		with patch.object(workbench_api, "frappe", _dict(db=_dict(get_value=Mock(return_value=None)))):
			rows, interval = workbench_api._checkpoint_intervals(card)
		self.assertEqual(interval, 120)
		self.assertEqual(len(rows), 6)
		self.assertEqual(rows[0]["from_time"], "2026-11-10 06:00:00")
		self.assertEqual(rows[-1]["to_time"], "2026-11-10 18:00:00")

	def test_overnight_shift_crosses_midnight(self):
		card = fake_card()
		card.shift_start = "2026-11-10 18:00:00"
		card.shift_end = "2026-11-11 06:00:00"
		with patch.object(workbench_api, "frappe", _dict(db=_dict(get_value=Mock(return_value=None)))):
			rows, _interval = workbench_api._checkpoint_intervals(card)
		self.assertEqual(len(rows), 6)
		self.assertEqual(rows[-1]["from_time"], "2026-11-11 04:00:00")
		self.assertEqual(rows[-1]["to_time"], "2026-11-11 06:00:00")

	def test_shift_type_custom_checkpoint_interval_is_used(self):
		with patch.object(workbench_api, "frappe", _dict(db=_dict(get_value=Mock(return_value=180)))):
			rows, interval = workbench_api._checkpoint_intervals(fake_card())
		self.assertEqual(interval, 180)
		self.assertEqual(len(rows), 4)
		self.assertEqual(rows[-1]["from_time"], "2026-11-10 15:00:00")

	def test_partial_final_checkpoint_is_preserved(self):
		card = fake_card()
		card.shift_end = "2026-11-10 17:00:00"
		with patch.object(workbench_api, "frappe", _dict(db=_dict(get_value=Mock(return_value=300)))):
			rows, _interval = workbench_api._checkpoint_intervals(card)
		self.assertEqual([(row["from_time"], row["to_time"]) for row in rows][-1], ("2026-11-10 16:00:00", "2026-11-10 17:00:00"))

	def test_different_job_cards_can_have_separate_entries_for_same_checkpoint(self):
		card = fake_card()
		job_one = fake_job([_dict(name="TL-1", from_time="2026-11-10 06:00:00", to_time="2026-11-10 08:00:00", qcmc_process_card="PC-1", qcmc_good_qty=10, qcmc_rejected_qty=1, qcmc_output_remarks="", qcmc_output_entered_at="", qcmc_output_entered_by="", qcmc_output_revision=1, qcmc_output_correction_history="[]")])
		job_two = fake_job([_dict(name="TL-2", from_time="2026-11-10 06:00:00", to_time="2026-11-10 08:00:00", qcmc_process_card="PC-1", qcmc_good_qty=20, qcmc_rejected_qty=2, qcmc_output_remarks="", qcmc_output_entered_at="", qcmc_output_entered_by="", qcmc_output_revision=1, qcmc_output_correction_history="[]")])
		job_two.name = "JC-2"
		job_two.production_item = "ITEM-2"
		card.jobs = [_dict(job_card="JC-1"), _dict(job_card="JC-2")]
		item_rows = [_dict(name="ITEM-1", stock_uom="Nos"), _dict(name="ITEM-2", stock_uom="Kg")]
		with patch.object(workbench_api, "frappe", _dict(db=_dict(get_value=Mock(return_value=None)), get_list=Mock(return_value=item_rows))), patch.object(workbench_api, "_job_output_standards", side_effect=lambda row: {"soph": None, "color_count": None, "output_item": row.production_item}), patch.object(output_api, "frappe", _dict(parse_json=json.loads)):
			result = workbench_api._production_output_summary(card, [job_one, job_two])
		self.assertEqual(len(result["checkpoints"][0]["entries"]), 2)
		self.assertEqual({row["uom"] for row in result["per_item"]}, {"Nos", "Kg"})
		self.assertEqual({row["job_card"] for row in result["checkpoints"][0]["entries"]}, {"JC-1", "JC-2"})

	def test_quantity_summary_separates_current_card_all_card_output_and_official_total(self):
		card = fake_card()
		job_card = fake_job([
			_dict(name="TL-CURRENT", from_time="2026-11-10 06:00:00", to_time="2026-11-10 08:00:00", qcmc_process_card="PC-1", qcmc_good_qty=10, qcmc_rejected_qty=1, qcmc_output_remarks="", qcmc_output_entered_at="", qcmc_output_entered_by="", qcmc_output_revision=1, qcmc_output_correction_history="[]"),
			_dict(name="TL-OTHER", from_time="2026-11-10 08:00:00", to_time="2026-11-10 10:00:00", qcmc_process_card="PC-2", qcmc_good_qty=20, qcmc_rejected_qty=2, qcmc_output_remarks="", qcmc_output_entered_at="", qcmc_output_entered_by="", qcmc_output_revision=1, qcmc_output_correction_history="[]"),
		])
		card.jobs = [_dict(job_card="JC-1")]
		with patch.object(workbench_api, "frappe", _dict(db=_dict(get_value=Mock(return_value=None)), get_list=Mock(return_value=[_dict(name="ITEM-1", stock_uom="Nos", item_name="Item One")]))), patch.object(workbench_api, "_job_output_standards", return_value={"soph": 10, "color_count": 2, "output_item": "ITEM-1"}), patch.object(output_api, "frappe", _dict(parse_json=json.loads)):
			result = workbench_api._production_output_summary(card, [job_card])["per_job"][0]
		self.assertEqual(result["good_qty"], 10)
		self.assertEqual(result["all_process_card_output_qty"], 33)
		self.assertEqual(result["official_completed_qty"], 20)
		self.assertEqual(result["target_qty"], 100)
		self.assertEqual(result["remaining_qty"], 47)

	@patch("qcmc_logic.api.job_card_time_log.frappe")
	@patch("qcmc_logic.api.job_card_time_log.now_datetime", return_value="2026-11-10 08:00:00")
	def test_participation_interval_can_overlap_output_and_is_not_reported_as_output(self, now, frappe):
		frappe.session.user = "foreman@example.com"
		job = fake_job([_dict(
			name="TL-PARTICIPATION",
			employee="EMP-1",
			from_time="2026-11-10 06:00:00",
			to_time="2026-11-10 08:00:00",
			completed_qty=0,
			qcmc_process_card="PC-1",
			qcmc_output_revision=0,
		)])
		job.total_completed_qty = 0
		frappe.parse_json.side_effect = json.loads

		output_api._save_operational_output(
			fake_card(), job, datetime(2026, 11, 10, 6), datetime(2026, 11, 10, 8), 10, 0,
		)

		self.assertEqual(len(output_api._checkpoint_output_rows(job, "PC-1")), 1)
		self.assertEqual(job.time_logs[0].employee, "EMP-1")


class TestOperationalCheckpointStorage(TestCase):
	@patch("qcmc_logic.api.job_card_time_log.frappe")
	@patch("qcmc_logic.api.job_card_time_log.now_datetime", return_value="2026-11-10 10:00:00")
	def test_two_employee_less_checkpoints_total_18000_and_retry_adds_no_quantity(self, now, frappe):
		frappe.session.user = "foreman@example.com"
		frappe.parse_json.side_effect = json.loads
		frappe.utils.get_datetime.side_effect = lambda value: value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
		job = fake_job([_dict(
			name="TL-OFFICIAL", from_time="2026-11-10 04:00:00",
			to_time="2026-11-10 06:00:00", completed_qty=20,
		)])
		first_start, first_end = datetime(2026, 11, 10, 6), datetime(2026, 11, 10, 8)
		second_start, second_end = datetime(2026, 11, 10, 8), datetime(2026, 11, 10, 10)

		output_api._save_operational_output(fake_card(), job, first_start, first_end, 10000, 0)
		output_api._save_operational_output(fake_card(), job, second_start, second_end, 8000, 0)
		_entry, duplicate = output_api._save_operational_output(
			fake_card(), job, second_start, second_end, 8000, 0,
		)

		self.assertTrue(duplicate)
		operational_rows = [row for row in job.time_logs if row.get("qcmc_process_card") == "PC-1"]
		self.assertEqual(len(operational_rows), 2)
		self.assertEqual(sum(row.qcmc_good_qty for row in operational_rows), 18000)
		self.assertEqual(sum(row.completed_qty for row in operational_rows), 0)
		self.assertTrue(all(not row.get("employee") for row in operational_rows))
		self.assertEqual(job.total_completed_qty, 20)

	@patch("qcmc_logic.api.job_card_time_log._validate_operation_output_limits")
	@patch("qcmc_logic.api.job_card_time_log._load_job_card")
	@patch("qcmc_logic.api.job_card_time_log._validate_output_interval")
	@patch("qcmc_logic.api.job_card_time_log._process_card_and_job")
	@patch("qcmc_logic.api.job_card_time_log.frappe")
	@patch("qcmc_logic.api.job_card_time_log.now_datetime", return_value="2026-11-10 08:00:00")
	def test_write_endpoint_uses_linked_card_checkpoint_and_keeps_official_total(self, now, frappe, process_card, validate_interval, load_job, validate_operation_limit):
		from qcmc_logic.api import process_card_workbench

		frappe.session.user = "foreman@example.com"
		frappe.parse_json.side_effect = json.loads
		frappe.utils.get_datetime.side_effect = lambda value: datetime.fromisoformat(str(value))
		card = fake_card()
		process_card.return_value = card
		validate_interval.return_value = (datetime(2026, 11, 10, 6), datetime(2026, 11, 10, 8))
		load_job.return_value = fake_job([_dict(name="TL-OLD", from_time="2026-11-10 04:00:00", to_time="2026-11-10 06:00:00", completed_qty=20)])
		with patch.object(process_card_workbench, "_checkpoint_intervals", side_effect=AssertionError("new intervals must not use fixed schedule slots")):
			result = output_api.save_process_card_output("PC-1", "JC-1", "2026-11-10 06:00:00", "2026-11-10 08:00:00", 9, 1)
		self.assertEqual(result["entry"]["good_qty"], 9)
		self.assertEqual(result["entry"]["rejected_qty"], 1)
		self.assertEqual(load_job.return_value.time_logs[-1].completed_qty, 0)
		self.assertEqual(load_job.return_value.total_completed_qty, 20)
		self.assertTrue(load_job.return_value.flags.qcmc_operational_checkpoint_update)
		frappe.db.sql.assert_called_once_with("select name from `tabJob Card` where name=%s for update", "JC-1")

	@patch("qcmc_logic.api.job_card_time_log._validate_operation_output_limits")
	@patch("qcmc_logic.api.job_card_time_log._validate_output_interval", return_value=(datetime(2026, 11, 10, 6, 30), datetime(2026, 11, 10, 7, 15)))
	@patch("qcmc_logic.api.job_card_time_log._process_card_and_job", return_value=fake_card())
	@patch("qcmc_logic.api.job_card_time_log._load_job_card")
	@patch("qcmc_logic.api.job_card_time_log.frappe")
	def test_non_checkpoint_interval_is_accepted(self, frappe, load_job, process_card, validate_interval, validate_operation_limit):
		from qcmc_logic.api import process_card_workbench
		frappe.utils.get_datetime.side_effect = lambda value: value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
		job = fake_job([_dict(name="TL-OFFICIAL", completed_qty=20, from_time="2026-11-10 04:00:00", to_time="2026-11-10 06:00:00")])
		load_job.return_value = job
		with patch.object(process_card_workbench, "_checkpoint_intervals", side_effect=AssertionError("fixed schedule must not gate writes")):
			result = output_api.save_process_card_output("PC-1", "JC-1", "2026-11-10 06:30", "2026-11-10 07:15", 9, 1)
		self.assertEqual(result["entry"]["from_time"], "2026-11-10 06:30:00")
		self.assertEqual(result["entry"]["to_time"], "2026-11-10 07:15:00")

	def test_output_calculation_uses_total_good_and_rejected_and_flags_overtime(self):
		with patch.object(workbench_api, "frappe", _dict()):
			result = workbench_api._output_calculation(100, 10, 55, 60)
		self.assertAlmostEqual(result["run_hours"], 2)
		self.assertEqual(result["remaining_minutes"], -60)
		self.assertTrue(result["negative_remaining"])

	def test_missing_soph_is_explicitly_unavailable(self):
		with patch.object(workbench_api, "frappe", _dict()):
			result = workbench_api._output_calculation(100, 0, 0, 120)
		self.assertFalse(result["soph_available"])
		self.assertIsNone(result["run_hours"])

	def test_negative_soph_is_rejected(self):
		with patch.object(workbench_api, "frappe") as frappe:
			frappe.throw.side_effect = ValueError("SOPH must be greater than zero")
			with self.assertRaisesRegex(ValueError, "SOPH must be greater than zero"):
				workbench_api._output_calculation(100, 0, -5, 120)

	@patch("qcmc_logic.api.job_card_time_log.save_process_card_output")
	@patch("qcmc_logic.api.job_card_time_log.frappe")
	def test_batch_save_reports_partial_success_and_rolls_back_only_failed_row(self, frappe, save_one):
		save_one.side_effect = [{"entry": {"time_log_id": "TL-1"}}, ValueError("Invalid interval")]
		result = output_api.save_process_card_output_batch([
			{"process_card": "PC-1", "job_card": "JC-1"},
			{"process_card": "PC-1", "job_card": "JC-2"},
		])
		self.assertTrue(result["results"][0]["success"])
		self.assertFalse(result["results"][1]["success"])
		self.assertEqual(result["success_count"], 1)
		frappe.db.savepoint.assert_any_call("qcmc_output_row_0")
		frappe.db.rollback.assert_called_once_with(save_point="qcmc_output_row_1")

	@patch("qcmc_logic.api.job_card_time_log.frappe")
	def test_duplicate_checkpoint_retry_is_idempotent_and_does_not_save_again(self, frappe):
		frappe.utils.get_datetime.side_effect = lambda value: datetime.fromisoformat(str(value))
		frappe.parse_json.side_effect = json.loads
		row = _dict(name="TL-1", from_time="2026-11-10 06:00:00", to_time="2026-11-10 08:00:00", completed_qty=0, qcmc_process_card="PC-1", qcmc_good_qty=10, qcmc_rejected_qty=1, qcmc_output_remarks="", qcmc_output_entered_at="", qcmc_output_entered_by="", qcmc_output_revision=1, qcmc_output_correction_history="[]")
		job = fake_job([row])
		job.save = Mock(side_effect=AssertionError("idempotent retry must not save"))
		entry, duplicate = output_api._save_operational_output(fake_card(), job, datetime(2026, 11, 10, 6), datetime(2026, 11, 10, 8), 10, 1, "")
		self.assertTrue(duplicate)
		self.assertEqual(entry["good_qty"], 10)
		job.save.assert_not_called()

	@patch("qcmc_logic.api.job_card_time_log.frappe")
	@patch("qcmc_logic.api.job_card_time_log.now_datetime", return_value="2026-11-10 08:00:00")
	def test_zero_checkpoint_is_stored_without_changing_native_completed_qty(self, now, frappe):
		frappe.session.user = "foreman@example.com"
		frappe.parse_json.side_effect = json.loads
		job = fake_job()
		row, duplicate = output_api._save_operational_output(
			fake_card(), job, datetime(2026, 11, 10, 6), datetime(2026, 11, 10, 8), 0, 0, "No production",
		)
		self.assertFalse(duplicate)
		self.assertEqual(row["good_qty"], 0)
		self.assertEqual(row["rejected_qty"], 0)
		self.assertEqual(job.time_logs[0].completed_qty, 0)
		self.assertEqual(job.total_completed_qty, 20)
		self.assertTrue(job.flags.qcmc_operational_checkpoint_update)
		self.assertEqual(job.time_logs[0].qcmc_process_card, "PC-1")
		self.assertEqual(job.time_logs[0].qcmc_output_entered_by, "foreman@example.com")

	@patch("qcmc_logic.api.job_card_time_log.frappe")
	@patch("qcmc_logic.api.job_card_time_log.now_datetime", return_value="2026-11-10 08:00:00")
	def test_good_and_rejected_values_keep_their_distinct_semantics(self, now, frappe):
		frappe.session.user = "foreman@example.com"
		frappe.parse_json.side_effect = json.loads
		job = fake_job()
		row, _duplicate = output_api._save_operational_output(
			fake_card(), job, datetime(2026, 11, 10, 6), datetime(2026, 11, 10, 8), 12.5, 1.25,
		)
		self.assertEqual(row["good_qty"], 12.5)
		self.assertEqual(row["rejected_qty"], 1.25)
		self.assertEqual(job.time_logs[0].completed_qty, 0)

	@patch("qcmc_logic.api.job_card_time_log.frappe")
	def test_negative_and_over_precision_quantities_are_rejected(self, frappe):
		frappe.throw.side_effect = ValueError
		with self.assertRaises(ValueError):
			output_api._decimal_checkpoint_qty(-1, "Good quantity", 2)
		with self.assertRaises(ValueError):
			output_api._decimal_checkpoint_qty("1.234", "Good quantity", 2)

	@patch("qcmc_logic.api.job_card_time_log.frappe")
	def test_operational_output_cannot_exceed_remaining_job_card_quantity(self, frappe):
		frappe.throw.side_effect = lambda message: (_ for _ in ()).throw(ValueError(message))
		job = fake_job([_dict(name="TL-OFFICIAL", completed_qty=20, from_time="2026-11-10 04:00:00", to_time="2026-11-10 06:00:00")])
		with self.assertRaisesRegex(ValueError, "exceed the Job Card quantity"):
			output_api._save_operational_output(fake_card(), job, datetime(2026, 11, 10, 6), datetime(2026, 11, 10, 8), 80, 1)

	@patch("qcmc_logic.api.job_card_time_log.frappe")
	@patch("qcmc_logic.api.job_card_time_log.now_datetime", return_value="2026-11-10 09:00:00")
	def test_correction_records_old_and_new_values_reason_actor_and_revision(self, now, frappe):
		from qcmc_logic.api import process_card_workbench

		frappe.session.user = "foreman@example.com"
		frappe.parse_json.side_effect = json.loads
		frappe.utils.get_datetime.side_effect = lambda value: datetime.fromisoformat(str(value))
		row = _dict(
			name="TL-1", from_time="2026-11-10 06:00:00", to_time="2026-11-10 08:00:00",
			completed_qty=0, qcmc_process_card="PC-1", qcmc_good_qty=10,
			qcmc_rejected_qty=2, qcmc_output_remarks="old", qcmc_output_revision=1,
			qcmc_output_entered_at="2026-11-10 08:00:00", qcmc_output_entered_by="first@example.com",
			qcmc_output_correction_history="[]",
		)
		job = fake_job([row])
		with patch.object(process_card_workbench, "_lock_process_card", return_value=fake_card()), patch.object(process_card_workbench, "_job_card") as validate_job, patch.object(output_api, "_load_job_card", return_value=job), patch.object(output_api, "_validate_operation_output_limits"):
			result = output_api.correct_process_card_output("PC-1", "JC-1", "TL-1", 1, 9, 3, "recounted", "Scale reading corrected")
		self.assertEqual(result["entry"]["good_qty"], 9)
		self.assertEqual(result["entry"]["revision"], 2)
		history = json.loads(row.qcmc_output_correction_history)
		self.assertEqual(history[0]["previous_good_qty"], 10)
		self.assertEqual(history[0]["revised_rejected_qty"], 3)
		self.assertEqual(history[0]["reason"], "Scale reading corrected")
		self.assertEqual(history[0]["user"], "foreman@example.com")
		self.assertEqual(job.total_completed_qty, 20)
		validate_job.assert_called_once()

	@patch("qcmc_logic.api.job_card_time_log.frappe")
	def test_stale_revision_and_locked_card_are_rejected(self, frappe):
		from qcmc_logic.api import process_card_workbench

		frappe.throw.side_effect = ValueError
		with patch.object(process_card_workbench, "_lock_process_card", return_value=fake_card()), patch.object(process_card_workbench, "_job_card"), patch.object(output_api, "_load_job_card", return_value=fake_job([_dict(name="TL-1", qcmc_process_card="PC-1", qcmc_output_revision=2)])):
			with self.assertRaises(ValueError):
				output_api.correct_process_card_output("PC-1", "JC-1", "TL-1", 1, 1, 0, reason="stale edit")
		with patch.object(process_card_workbench, "_lock_process_card", return_value=fake_card("Approved")):
			with self.assertRaises(ValueError):
				output_api._process_card_and_job("PC-1", "JC-1")

	@patch("qcmc_logic.api.job_card_time_log.frappe")
	def test_unlinked_job_card_cannot_be_used(self, frappe):
		from qcmc_logic.api import process_card_workbench

		frappe.throw.side_effect = ValueError
		card = fake_card()
		with patch.object(process_card_workbench, "_lock_process_card", return_value=card), patch.object(process_card_workbench, "_job_card") as validate_job:
			with self.assertRaises(ValueError):
				output_api._process_card_and_job("PC-1", "JC-OTHER")
		validate_job.assert_not_called()

	@patch("qcmc_logic.customs.job_card.frappe")
	def test_operational_only_save_does_not_call_progressive_work_order_sync(self, frappe):
		from qcmc_logic.customs.job_card import sync_non_final_operation_progress
		doc = _dict(flags=_dict(qcmc_operational_checkpoint_update=True))
		sync_non_final_operation_progress(doc, "on_update")
		frappe.get_doc.assert_not_called()

	@patch("qcmc_logic.customs.job_card.frappe")
	def test_direct_add_edit_or_delete_of_hidden_output_fields_is_rejected(self, frappe):
		from qcmc_logic.customs.job_card import prevent_untracked_output_checkpoint_changes

		frappe.throw.side_effect = ValueError
		new_row = _dict(name="TL-1", qcmc_process_card="PC-1", qcmc_good_qty=1, qcmc_output_revision=1)
		new_doc = _dict(time_logs=[new_row], flags=_dict(), get_doc_before_save=lambda: None, get=lambda field: [new_row])
		with self.assertRaises(ValueError):
			prevent_untracked_output_checkpoint_changes(new_doc)

		old_row = _dict(name="TL-1", qcmc_process_card="PC-1", qcmc_good_qty=1, qcmc_output_revision=1)
		new_row = _dict(name="TL-1", qcmc_process_card="PC-1", qcmc_good_qty=2, qcmc_output_revision=1)
		previous = _dict(time_logs=[old_row], get=lambda field: [old_row])
		doc = _dict(time_logs=[new_row], flags=_dict(), get_doc_before_save=lambda: previous, get=lambda field: [new_row])
		with self.assertRaises(ValueError):
			prevent_untracked_output_checkpoint_changes(doc)

		doc.time_logs = []
		with self.assertRaises(ValueError):
			prevent_untracked_output_checkpoint_changes(doc)

		previous = _dict(time_logs=[_dict(
			name="TL-1", from_time="2026-11-10 06:00:00", to_time="2026-11-10 08:00:00",
			completed_qty=0, qcmc_process_card="PC-1", qcmc_good_qty=1, qcmc_output_revision=1,
		)])
		changed_time = _dict(
			name="TL-1", from_time="2026-11-10 06:30:00", to_time="2026-11-10 08:00:00",
			completed_qty=0, qcmc_process_card="PC-1", qcmc_good_qty=1, qcmc_output_revision=1,
		)
		doc = _dict(time_logs=[changed_time], flags=_dict(), get_doc_before_save=lambda: previous, get=lambda field: [changed_time])
		with self.assertRaises(ValueError):
			prevent_untracked_output_checkpoint_changes(doc)

	@patch("qcmc_logic.customs.job_card.frappe")
	def test_workbench_flag_allows_audited_checkpoint_mutation(self, frappe):
		from qcmc_logic.customs.job_card import prevent_untracked_output_checkpoint_changes
		doc = _dict(flags=_dict(qcmc_operational_checkpoint_update=True))
		prevent_untracked_output_checkpoint_changes(doc)
		frappe.throw.assert_not_called()
