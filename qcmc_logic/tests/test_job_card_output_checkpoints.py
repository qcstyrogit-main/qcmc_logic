from unittest import TestCase
from unittest.mock import patch
from datetime import datetime

from frappe import _dict

from qcmc_logic.api.job_card_time_log import save_output_checkpoint


def make_doc(rows=None):
	doc = _dict(
		name="JC-OUTPUT",
		work_order="WO-OUTPUT",
		operation_id="WO-OP-OUTPUT",
		docstatus=0,
		status="Open",
		for_quantity=18000,
		total_completed_qty=sum(row.completed_qty for row in rows or []),
		total_time_in_mins=0,
		company="Test Co",
		production_item="ITEM-OUTPUT",
		workstation="WS-OUTPUT",
		time_logs=rows or [],
		precision=lambda field: 2,
	)

	def append(field, values):
		row = _dict(name=f"NEW-{len(doc.time_logs) + 1}", idx=len(doc.time_logs) + 1, employee=None, **values)
		doc.time_logs.append(row)
		return row

	def save():
		return None

	doc.append = append
	doc.save = save
	return doc


class TestOutputCheckpoints(TestCase):
	@patch("qcmc_logic.api.job_card_time_log._parse_checkpoint_time", side_effect=lambda value, field: datetime.fromisoformat(value))
	@patch("qcmc_logic.api.job_card_time_log._auth", return_value="foreman@example.com")
	@patch("qcmc_logic.api.job_card_time_log._context")
	@patch("qcmc_logic.api.job_card_time_log._load_job_card")
	@patch("qcmc_logic.api.job_card_time_log.frappe")
	def test_two_shifts_record_18000_without_employee_and_retry_is_idempotent(self, frappe, load, context, auth, parse_time):
		first = make_doc()
		load.side_effect = [first, first, first]
		frappe.utils.get_datetime.side_effect = lambda value: datetime.fromisoformat(str(value))
		context.side_effect = lambda doc, duplicate_request=False, affected_row=None: {
			"success": True, "duplicate_request": duplicate_request,
			"time_log": affected_row,
		}

		save_output_checkpoint("JC-OUTPUT", "2026-11-09 06:00:00", "2026-11-09 08:00:00", 10000)
		save_output_checkpoint("JC-OUTPUT", "2026-11-09 08:00:00", "2026-11-09 10:00:00", 8000)
		result = save_output_checkpoint("JC-OUTPUT", "2026-11-09 08:00:00", "2026-11-09 10:00:00", 8000)

		self.assertTrue(result["duplicate_request"])
		self.assertEqual(len(first.time_logs), 2)
		self.assertEqual(sum(row.completed_qty for row in first.time_logs), 18000)
		self.assertTrue(all(row.employee is None for row in first.time_logs))
		self.assertEqual(frappe.db.sql.call_count, 3)
