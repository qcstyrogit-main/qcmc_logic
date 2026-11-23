"""Isolated checks for the confirmed Logistics/Sales decision sequence."""

from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

import frappe

from qcmc_logic.api import delivery_schedule_collaboration_v2 as collaboration
from qcmc_logic.api import delivery_workbench_collaboration as workbench_collaboration


class FakeSchedule(SimpleNamespace):
	def get(self, fieldname, default=None):
		return getattr(self, fieldname, default)

	def set(self, fieldname, value):
		setattr(self, fieldname, value)

	def add_comment(self, *args, **kwargs):
		return None


class TestScheduleConfirmations(TestCase):
	def test_existing_logistics_reason_list_is_validated_for_schedule_records(self):
		with patch("qcmc_logic.api.delivery_confirmation_service._get_logistics_reason_code_map",
			return_value={"OK": "Good to go", "SA": "Stock Availability"}):
			self.assertEqual(collaboration._clean_logistics_reason("SA"), "SA")
			self.assertEqual(collaboration._clean_logistics_reason(""), "")
			with patch.object(collaboration, "_", side_effect=lambda message: message), \
				patch.object(frappe, "throw", side_effect=lambda message, exc=frappe.ValidationError: (_ for _ in ()).throw(exc(message))):
				with self.assertRaisesRegex(frappe.ValidationError, "valid Logistics reason"):
					collaboration._clean_logistics_reason("UNKNOWN")

	def test_schedule_read_model_never_counts_draft_dn_as_actual_delivery(self):
		row = frappe._dict(name="SCHED-PROMISE", original_qty=10, cancelled_dn_qty=0)
		fulfillment = frappe._dict(draft_dn_qty=4, submitted_dn_qty=2, submitted_dn_count=1,
			cancelled_dn_qty=3, last_submitted_delivery_date="2026-11-18")
		collaboration._apply_fulfillment_read_model(row, fulfillment)
		self.assertEqual(row.draft_dn_qty, 4)
		self.assertEqual(row.submitted_dn_qty, 2)
		self.assertEqual(row.cancelled_dn_qty, 3)
		self.assertEqual(row.actual_delivered_qty, 2)
		self.assertEqual(row.original_promise_commitment, "SCHED-PROMISE")
		self.assertEqual(row.last_submitted_delivery_date, "2026-11-18")

	def test_derived_schedule_has_no_new_original_promise_identity(self):
		row = frappe._dict(name="SCHED-TRANSFER", original_qty=0)
		collaboration._apply_fulfillment_read_model(row, None)
		self.assertIsNone(row.original_promise_commitment)
		self.assertEqual(row.draft_dn_qty, 0)
		self.assertEqual(row.actual_delivered_qty, 0)

	def test_edit_lease_accepts_v2_draft_without_legacy_stock_confirmation(self):
		doc = SimpleNamespace(name="DN-V2", docstatus=0, workflow_state="Draft",
			items=[frappe._dict(custom_so_delivery_schedule="SCHED-1")],
			check_permission=lambda action: None)
		with patch.object(frappe, "session", SimpleNamespace(user="sales@example.com")), \
			patch.object(frappe, "get_roles", return_value=["Sales Coordinator"]), \
			patch.object(frappe, "get_doc", return_value=doc), \
			patch.object(frappe, "has_permission", return_value=True), \
			patch("qcmc_logic.api.delivery_schedule_revision._validate_v2_sales_edit_draft") as validate_v2, \
			patch("qcmc_logic.api.delivery_confirmation_service._validate_sales_review_delivery_note") as validate_legacy:
			self.assertIs(workbench_collaboration._authorize("DN-V2", edit=True), doc)
		validate_v2.assert_called_once_with(doc)
		validate_legacy.assert_not_called()

	def make_schedule(self, **overrides):
		values = dict(
			name="SCHED-1", modified="v1", delivery_date="2026-11-20", planned_qty=10000, original_qty=10000,
			quantity_changes=0, current_total=10000, original_promise_date="2026-11-20",
			source_schedule=None, source_date=None, movement_transaction_id=None,
			sales_proposed_qty=4000, sales_remarks="Accepted amount",
			logistics_committed_qty=5000, logistics_remarks="Confirmed capacity",
			logistics_transfer_qty=0, logistics_destination_date=None,
			sales_confirmed_by=None, logistics_confirmed_by="logistics@example.com",
			final_qty=None, confirmation_status="In Review", finalized_at=None,
		)
		values.update(overrides)
		return FakeSchedule(**values)

	def test_unreconciled_history_cannot_be_changed_or_confirmed(self):
		row = self.make_schedule(history_status="Unreconciled")
		with patch.object(collaboration, "_", side_effect=lambda message: message), \
			patch.object(frappe, "throw", side_effect=frappe.ValidationError):
			with self.assertRaises(frappe.ValidationError):
				collaboration._assert_verified_history(row)

	def test_verified_history_allows_v2_mutation_gate(self):
		row = self.make_schedule(history_status="Verified")
		self.assertIsNone(collaboration._assert_verified_history(row))

	def test_sales_can_finalize_less_than_logistics_confirmed(self):
		row = self.make_schedule()
		item = SimpleNamespace(precision=lambda field: 0)
		so = object()
		with patch.object(collaboration, "_load_locked", return_value=(row, so, item)), \
			patch.object(collaboration, "_assert_open"), patch.object(collaboration, "_save"), \
			patch("qcmc_logic.api.delivery_schedule_service._split_unfinalized_schedule_balance") as split_balance, \
			patch.object(collaboration, "now_datetime", return_value="2026-11-19 10:00:00"), \
			patch.object(frappe, "session", SimpleNamespace(user="sales@example.com")):
			result = collaboration._confirm("SCHED-1", "v1", "Sales")
			retry = collaboration._confirm("SCHED-1", "v1", "Sales")
		self.assertEqual(row.final_qty, 4000)
		self.assertEqual(row.confirmation_status, "Finalized")
		self.assertEqual(result["final_qty"], 4000)
		split_balance.assert_called_once_with(row, so, item, 4000, 0)
		self.assertFalse(retry["changed"])

	def test_sales_confirmation_retry_is_idempotent_after_finalization(self):
		row = self.make_schedule(sales_confirmed_by="sales@example.com", final_qty=4000,
			confirmation_status="Finalized", logistics_transfer_qty=0)
		with patch.object(collaboration, "_load_locked", return_value=(row, object(), object())), \
			patch.object(collaboration, "_assert_open", side_effect=AssertionError("retry must not reopen finalized row")) as assert_open, \
			patch.object(frappe, "session", SimpleNamespace(user="sales@example.com")):
			result = collaboration._confirm("SCHED-1", "v1", "Sales")
		self.assertFalse(result["changed"])
		assert_open.assert_not_called()

	def test_proceed_to_dr_uses_finalized_schedule_without_sales_order_version_flag(self):
		row = self.make_schedule(name="SCHED-FINAL", modified="current", final_qty=4,
			confirmation_status="Finalized", sales_confirmed_by="sales@example.com",
			logistics_confirmed_by="logistics@example.com")
		so = SimpleNamespace(name="26-00038")
		item = SimpleNamespace(name="SOI-1")
		with patch.object(collaboration, "_require_role"), \
			patch.object(collaboration, "_load_locked", return_value=(row, so, item)), \
			patch("qcmc_logic.api.delivery_schedule_service.quantity_state", return_value={
				"draft_allocated_by_schedule": {"SCHED-FINAL": 0}}), \
			patch("qcmc_logic.api.delivery_schedule_service.create_draft_delivery_notes",
				return_value={"created": ["MAT-DN-TEST"]}) as create:
			result = collaboration.proceed_to_dr([{"schedule": row.name, "modified": "current",
				"draft_allocated_qty": 0}])
		self.assertEqual(result, {"created": ["MAT-DN-TEST"]})
		create.assert_called_once_with({"SCHED-FINAL": 4},
			{"SCHED-FINAL": {"modified": "current", "draft_allocated_qty": 0}})

	def test_sales_creates_dn_details_within_logistics_confirmed_quantity(self):
		row = self.make_schedule(name="SCHED-READY", modified="current", planned_qty=10,
			current_total=10, logistics_committed_qty=4, logistics_confirmed_by="logistics@example.com",
			sales_confirmed_by=None, final_qty=None, confirmation_status="In Review")
		item = SimpleNamespace(name="SOI-1", precision=lambda field: 0)
		so = SimpleNamespace(name="26-00038")
		with patch.object(collaboration, "_require_role"), \
			patch.object(collaboration, "_load_locked", return_value=(row, so, item)), \
			patch("qcmc_logic.api.delivery_schedule_service.quantity_state", return_value={
				"draft_allocated_by_schedule": {"SCHED-READY": 0}}), \
			patch("qcmc_logic.api.delivery_schedule_service._split_unfinalized_schedule_balance") as split, \
			patch.object(collaboration, "_save"), \
			patch.object(collaboration, "now_datetime", return_value="2026-11-23 08:00:00"), \
			patch.object(frappe, "session", SimpleNamespace(user="sales@example.com")), \
			patch("qcmc_logic.api.delivery_schedule_service.create_draft_delivery_notes",
				return_value={"delivery_notes": ["DN-TEST"]}) as create:
			result = collaboration.proceed_to_dr([{"schedule": row.name, "modified": "current",
				"draft_allocated_qty": 0, "quantity": 3}])
		self.assertEqual(result, {"delivery_notes": ["DN-TEST"]})
		self.assertEqual(row.final_qty, 3)
		self.assertEqual(row.sales_confirmed_by, "sales@example.com")
		self.assertEqual(row.confirmation_status, "Finalized")
		split.assert_called_once_with(row, so, item, 3, 0)
		create.assert_called_once_with({"SCHED-READY": 3},
			{"SCHED-READY": {"modified": "current", "draft_allocated_qty": 0}})

	def test_sales_dn_quantity_cannot_exceed_logistics_commitment(self):
		item = SimpleNamespace(precision=lambda field: 0)
		with patch.object(collaboration, "_", side_effect=lambda message: message), \
			patch.object(frappe, "throw", side_effect=lambda message, exc=frappe.ValidationError: (_ for _ in ()).throw(exc(message))):
			with self.assertRaisesRegex(frappe.ValidationError, "Sales Final Qty cannot exceed Logistics Confirmed QTY"):
				collaboration.validate_sales_final_quantity(5, 4, item, 10)

	def test_logistics_autosave_also_confirms_commitment(self):
		with patch.object(collaboration, "_save_commitment", return_value={"modified": "v2", "changed": True}) as save, \
			patch.object(collaboration, "_confirm", return_value={"logistics_confirmed_by": "logistics@example.com"}) as confirm:
			result = collaboration.save_logistics_commitment("SCHED-1", "v1", 5000,
				"Ready", transfer_qty=None, destination_date=None, reason_code="OK")
		self.assertEqual(result["logistics_confirmed_by"], "logistics@example.com")
		save.assert_called_once_with("SCHED-1", "v1", "Logistics", 5000, "Ready",
			transfer_qty=None, destination_date=None, reason_code="OK")
		confirm.assert_called_once_with("SCHED-1", "v2", "Logistics")

	def test_logistics_confirmation_does_not_finalize_for_sales(self):
		row = self.make_schedule(logistics_confirmed_by=None, sales_confirmed_by=None,
			logistics_transfer_qty=0)
		item = SimpleNamespace(precision=lambda field: 0)
		with patch.object(collaboration, "_load_locked", return_value=(row, object(), item)), \
			patch.object(collaboration, "_assert_open"), patch.object(collaboration, "_save"), \
			patch.object(frappe, "session", SimpleNamespace(user="logistics@example.com")):
			result = collaboration._confirm("SCHED-1", "v1", "Logistics")
		self.assertEqual(row.logistics_confirmed_by, "logistics@example.com")
		self.assertIsNone(row.final_qty)
		self.assertEqual(row.confirmation_status, "In Review")
		self.assertIsNone(result["final_qty"])

	def test_sales_proposal_change_preserves_logistics_confirmation(self):
		row = self.make_schedule(sales_proposed_qty=5000)
		item = SimpleNamespace(precision=lambda field: 0)
		with patch.object(collaboration, "_load_locked", return_value=(row, object(), item)), \
			patch.object(collaboration, "_assert_open"), patch.object(collaboration, "_save"):
			collaboration._save_commitment("SCHED-1", "v1", "Sales", 3000, "Sales revision")
		self.assertEqual(row.sales_proposed_qty, 3000)
		self.assertEqual(row.logistics_confirmed_by, "logistics@example.com")

	def test_logistics_commitment_change_invalidates_sales_finalization(self):
		row = self.make_schedule(sales_confirmed_by="sales@example.com", final_qty=4000,
			logistics_confirmed_by="logistics@example.com")
		item = SimpleNamespace(name="SOI-1", precision=lambda field: 0)
		state = {"available_scheduled_qty": {"SCHED-1": 10000}}
		with patch.object(collaboration, "_load_locked", return_value=(row, object(), item)), \
			patch.object(collaboration, "_assert_open"), patch.object(collaboration, "_save"), \
			patch.object(collaboration, "_", side_effect=lambda value: value), \
			patch.object(frappe, "session", SimpleNamespace(user="logistics@example.com")), \
			patch("qcmc_logic.api.delivery_schedule_service.quantity_state", return_value=state):
			collaboration._save_commitment("SCHED-1", "v1", "Logistics", 4500, "Capacity revision")
		self.assertIsNone(row.logistics_confirmed_by)
		self.assertIsNone(row.sales_confirmed_by)
		self.assertIsNone(row.final_qty)

	def test_logistics_transfer_proposal_does_not_move_schedule_totals(self):
		row = self.make_schedule(logistics_confirmed_by=None)
		item = SimpleNamespace(name="SOI-1", precision=lambda field: 0)
		state = {"available_scheduled_qty": {"SCHED-1": 10000}}
		with patch.object(collaboration, "_load_locked", return_value=(row, object(), item)), \
			patch.object(collaboration, "_assert_open"), patch.object(collaboration, "_save"), \
			patch("qcmc_logic.api.delivery_schedule_service.quantity_state", return_value=state), \
			patch("qcmc_logic.api.delivery_schedule_service._apply_schedule_transfer_locked") as apply_transfer:
			collaboration._save_commitment("SCHED-1", "v1", "Logistics", 8000,
				"Move the free quantity", transfer_qty=2000, destination_date="2026-11-25")
		self.assertEqual(row.current_total, 10000)
		self.assertEqual(row.planned_qty, 10000)
		self.assertEqual(row.logistics_transfer_qty, 2000)
		self.assertEqual(row.logistics_destination_date, "2026-11-25")
		apply_transfer.assert_not_called()
