"""Site-free checks for atomic draft DR quantity revisions."""

from unittest import TestCase
from unittest.mock import MagicMock, patch

import frappe

from qcmc_logic.api import delivery_schedule_revision as revision
from qcmc_logic.api import sales_order_schedule_split as split
from qcmc_logic.api import delivery_workbench_collaboration as collaboration
from qcmc_logic.api import delivery_confirmation_service as confirmation


class TestDeliveryScheduleRevision(TestCase):
	def setUp(self):
		self.item = frappe._dict(name="DNI-1", item_code="ITEM-1", qty=150, so_detail="SOI-1",
			against_sales_order="SO-1", custom_sales_final_qty=150, precision=lambda field: 3)
		self.source = frappe._dict(name="SOI-1", parent="SO-1", qty=150, delivered_qty=0)
		self.so = MagicMock(name="SO-1")
		self.so.name = "SO-1"
		self.so.items = [self.source]
		self.so.check_permission = MagicMock()
		self.doc = MagicMock(items=[self.item], modified="v1", name="DN-1")
		self.doc.check_permission = MagicMock()
		self.db = MagicMock()
		self.db.savepoint = MagicMock()
		self.db.rollback = MagicMock()
		self.split_calls = []
		def apply_split(*args, **kwargs):
			self.split_calls.append(kwargs)
			self.source.qty = kwargs["retained_quantity"]
			return {"destination": "SOI-DEST"}
		self.patches = [
			patch.object(revision, "_", side_effect=lambda value: value),
			patch.object(frappe, "throw", side_effect=lambda message, exc=frappe.ValidationError, **kwargs: (_ for _ in ()).throw(exc(message))),
			patch.object(frappe, "db", self.db),
			patch.object(frappe, "get_doc", return_value=self.so),
			patch.object(frappe, "get_system_settings", return_value="Banker's Rounding"),
			patch.object(confirmation, "_validate_sales_approval_role"),
			patch.object(confirmation, "_get_locked_delivery_note", return_value=self.doc),
			patch.object(confirmation, "_validate_sales_review_delivery_note"),
			patch.object(confirmation, "_get_logistics_committed_qty", return_value=150),
			patch.object(split, "preview_split", side_effect=lambda *a, **kw: {"state": "fresh-state"}),
			patch.object(split, "split_schedule", side_effect=apply_split),
			patch.object(collaboration, "bind_edit"),
			patch.object(collaboration, "notify_change"),
		]
		for patcher in self.patches:
			patcher.start()
			self.addCleanup(patcher.stop)

	def test_repeated_reductions_transfer_only_each_increment(self):
		first = revision.revise_delivery_note_item("DN-1", "DNI-1", 120, "2026-11-12", "v1", "lease")
		self.assertEqual(first["deferred_qty"], 30)
		self.assertEqual(self.split_calls[-1]["retained_quantity"], 120)
		self.item.qty = 120
		self.doc.modified = "v2"
		second = revision.revise_delivery_note_item("DN-1", "DNI-1", 115, "2026-11-12", "v2", "lease")
		self.assertEqual(second["deferred_qty"], 5)
		self.assertEqual(self.split_calls[-1]["retained_quantity"], 115)
		self.assertEqual(self.item.qty, 115)
		self.assertEqual(self.split_calls[-1]["delivery_date"], "2026-11-12")
		self.assertEqual(self.split_calls[-1]["expected_state"], "fresh-state")

	def test_split_failure_rolls_back_the_delivery_note_write(self):
		with patch.object(split, "split_schedule", side_effect=RuntimeError("financial invariant")):
			with self.assertRaisesRegex(RuntimeError, "financial invariant"):
				revision.revise_delivery_note_item("DN-1", "DNI-1", 120, "2026-11-12", "v1", "lease")
		self.db.rollback.assert_called_once_with(save_point="sales_delivery_revision")

	def test_revision_cannot_exceed_logistics_commitment(self):
		with self.assertRaises(frappe.ValidationError):
			revision.revise_delivery_note_item("DN-1", "DNI-1", 151, "2026-11-12", "v1", "lease")
		self.doc.save.assert_not_called()

	def test_v2_draft_revision_bypasses_legacy_stock_confirmation_gate(self):
		self.item.custom_so_delivery_schedule = "SCHED-1"
		self.doc.workflow_state = "Draft"
		with patch.object(revision, "_validate_v2_sales_edit_draft") as validate_v2, \
			patch("qcmc_logic.api.delivery_schedule_service.revise_draft_delivery_note_item",
				return_value={"saved": True}) as revise_v2:
			result = revision.revise_delivery_note_item("DN-1", "DNI-1", 120, "2026-11-12",
				"v1", "lease", remarks="Customer requested lower quantity")
		self.assertEqual(result, {"saved": True})
		validate_v2.assert_called_once_with(self.doc)
		confirmation._validate_sales_review_delivery_note.assert_not_called()
		self.doc.check_permission.assert_not_called()
		revise_v2.assert_called_once_with(self.doc, self.item, 120, "2026-11-12",
			remarks="Customer requested lower quantity")

	def test_v2_sales_revision_requires_unnumbered_draft_and_sales_role(self):
		self.doc.workflow_state = "To Deliver and Bill"
		with patch.object(revision, "_", side_effect=lambda message: message), \
			patch.object(frappe, "get_roles", return_value=["Sales Coordinator"]), \
			patch.object(frappe, "has_permission", return_value=True), \
			patch.object(frappe, "throw", side_effect=lambda message, exc=frappe.ValidationError: (_ for _ in ()).throw(exc(message))):
			with self.assertRaisesRegex(frappe.ValidationError, "unnumbered V2 Draft"):
				revision._validate_v2_sales_edit_draft(self.doc)

		self.doc.workflow_state = "Draft"
		self.doc.custom_dr_number = "DR-1"
		with patch.object(revision, "_", side_effect=lambda message: message), \
			patch.object(frappe, "get_roles", return_value=["Sales Coordinator"]), \
			patch.object(frappe, "has_permission", return_value=True), \
			patch.object(frappe, "throw", side_effect=lambda message, exc=frappe.ValidationError: (_ for _ in ()).throw(exc(message))):
			with self.assertRaisesRegex(frappe.ValidationError, "unnumbered V2 Draft"):
				revision._validate_v2_sales_edit_draft(self.doc)

	def test_v2_whole_dn_move_dispatches_without_legacy_stock_confirmation_gate(self):
		self.item.custom_so_delivery_schedule = "SCHED-1"
		self.doc.workflow_state = "Draft"
		with patch.object(revision, "_validate_v2_sales_edit_draft") as validate_v2, \
			patch("qcmc_logic.api.delivery_schedule_service.move_draft_delivery_note",
				return_value={"saved": True}) as move_v2:
			result = revision.move_delivery_note_date("DN-1", "2026-11-14", "v1", "lease",
				remarks="Customer requested whole-DN date change")
		self.assertEqual(result, {"saved": True})
		validate_v2.assert_called_once_with(self.doc)
		confirmation._validate_sales_review_delivery_note.assert_not_called()
		self.doc.check_permission.assert_not_called()
		move_v2.assert_called_once_with(self.doc, "2026-11-14",
			remarks="Customer requested whole-DN date change")
