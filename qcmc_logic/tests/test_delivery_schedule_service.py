from unittest import TestCase
from unittest.mock import Mock, patch
from types import ModuleType, SimpleNamespace

import frappe

from qcmc_logic.api import delivery_schedule_service as service
from qcmc_logic.api import delivery_schedule_collaboration_v2 as schedule_collaboration
from qcmc_logic.api import sales_order_scheduling_service as scheduling_report


class TestDeliveryScheduleService(TestCase):
	def test_v2_whole_dn_move_rejects_legacy_workflow_state(self):
		doc = SimpleNamespace(docstatus=0, workflow_state="For Stock Confirmation", items=[object()])
		with patch.object(service, "_", side_effect=lambda message: message), \
			patch.object(frappe, "throw", side_effect=lambda message, exc=frappe.ValidationError: (_ for _ in ()).throw(exc(message))):
			with self.assertRaisesRegex(frappe.ValidationError, "unnumbered Draft"):
				service.move_draft_delivery_note(doc, "2026-11-20", remarks="Customer requested movement")

	def test_v2_whole_dn_move_rejects_released_or_numbered_dn(self):
		for state, number in (("To Deliver and Bill", None), ("Draft", "DR-1")):
			doc = SimpleNamespace(docstatus=0, workflow_state=state, items=[object()],
				get=lambda field, number=number: number if field == "custom_dr_number" else None)
			with self.subTest(state=state, number=number), \
				patch.object(service, "_", side_effect=lambda message: message), \
				patch.object(frappe, "throw", side_effect=lambda message, exc=frappe.ValidationError: (_ for _ in ()).throw(exc)):
				with self.assertRaises(frappe.ValidationError):
					service.move_draft_delivery_note(doc, "2026-11-20", remarks="Authorized correction")

	def test_schedule_total_excludes_dn_fulfillment_and_reservations(self):
		state = service.calculate_schedule_quantities(10000, -5000, 5000, 0, 0)
		self.assertEqual(state["total"], 5000)
		self.assertEqual(state["available_for_new_dr"], 0)
		self.assertEqual(state["submitted_qty"], 5000)

	def test_schedule_quantity_accounting_rejects_duplicate_allocation(self):
		with patch.object(service, "_", side_effect=lambda message: message), \
			patch.object(service.frappe, "throw", side_effect=lambda message, exc=frappe.ValidationError: (_ for _ in ()).throw(exc(message))):
			with self.assertRaisesRegex(frappe.ValidationError, "over-allocated"):
				service.calculate_schedule_quantities(100, 0, 60, 50, 0)

	def test_dn_allocation_includes_submitted_quantity_before_accepting_new_draft(self):
		with patch.object(service, "_", side_effect=lambda message: message), \
			patch.object(service.frappe, "throw", side_effect=lambda message, exc=frappe.ValidationError: (_ for _ in ()).throw(exc(message))):
			with self.assertRaisesRegex(frappe.ValidationError, "over-allocated"):
				service.validate_schedule_allocation(10000, 6000, 0, 5000, 0)

	def test_dn_allocation_counts_current_dn_once_and_respects_precision(self):
		state = service.validate_schedule_allocation(10000, 6000, 1000, 3000, 0)
		self.assertEqual(state["available_for_new_dr"], 0)

	def test_so_balance_does_not_reopen_submitted_scheduled_demand(self):
		state = service.calculate_so_schedule_balance(10000, 10000, 6000, 6000, 0)
		self.assertEqual(state["unlinked_fulfillment_qty"], 0)
		self.assertEqual(state["unscheduled_qty"], 0)

	def test_so_balance_subtracts_unlinked_fulfillment_once(self):
		state = service.calculate_so_schedule_balance(10000, 3000, 6000, 2000, 0)
		self.assertEqual(state["unlinked_fulfillment_qty"], 4000)
		self.assertEqual(state["unscheduled_qty"], 3000)

	def test_multiple_promise_origins_are_preserved_when_transferring(self):
		rows = [
			frappe._dict(operation_type="Initial Commitment", source_schedule=None, destination_schedule="SCHED-1",
				promise_commitment="SCHED-1", promise_date="2026-11-01", promise_qty=3000),
			frappe._dict(operation_type="Transfer In", source_schedule="SCHED-OLD", destination_schedule="SCHED-1",
				promise_commitment="SCHED-2", promise_date="2026-11-01", promise_qty=4000),
			frappe._dict(operation_type="Transfer Out", source_schedule="SCHED-1", destination_schedule="SCHED-2",
				promise_commitment="SCHED-1", promise_date="2026-11-01", promise_qty=1000),
		]
		with patch.object(service.frappe, "get_all", return_value=rows):
			origins = service._allocate_promise_attributions("SCHED-1", 5000)
		self.assertEqual(origins, [("SCHED-1", "2026-11-01", service.Decimal(2000)),
			("SCHED-2", "2026-11-01", service.Decimal(3000))])

	def test_quantity_adjustment_reduces_only_the_matching_promise_cohort_balance(self):
		rows = [
			frappe._dict(operation_type="Initial Commitment", source_schedule=None,
				destination_schedule="SCHED-1", promise_commitment="SCHED-1",
				promise_date="2026-11-01", promise_qty=10000),
			frappe._dict(operation_type="Quantity Adjustment", source_schedule="SCHED-1",
				destination_schedule=None, promise_commitment="SCHED-1",
				promise_date="2026-11-01", promise_qty=2500),
		]
		with patch.object(service.frappe, "get_all", return_value=rows) as get_all:
			origins = service._schedule_promise_attributions("SCHED-1")
		self.assertEqual(origins, {("SCHED-1", "2026-11-01"): service.Decimal(7500)})
		self.assertIn("Quantity Adjustment", get_all.call_args.kwargs["filters"]["operation_type"][1])

	def test_derived_schedule_persisted_provenance_is_compared_as_immutable(self):
		values = frappe._dict(
			original_delivery_date="2026-11-16", original_qty=0,
			original_promise_date="2026-11-14", original_promise_qty=0,
			source_schedule="SCHED-SOURCE", source_date="2026-11-14",
			movement_transaction_id="move-123",
		)
		doc = frappe._dict(name="SCHED-DERIVED", **values)
		db = SimpleNamespace(get_value=Mock(return_value=values))
		with patch.object(frappe, "db", db):
			service._validate_original_schedule_fields_unchanged(doc)
		self.assertEqual(db.get_value.call_args.args[2], list(service.SCHEDULE_ORIGINAL_FIELDS))

		doc.source_schedule = "OTHER-SCHEDULE"
		with patch.object(service, "_", side_effect=lambda message: message), \
			patch.object(frappe, "db", db), \
			patch.object(frappe, "throw", side_effect=lambda message, exc=frappe.PermissionError: (_ for _ in ()).throw(exc(message))):
			with self.assertRaisesRegex(frappe.PermissionError, "immutable"):
				service._validate_original_schedule_fields_unchanged(doc)

	def test_sales_final_qty_may_be_below_logistics_confirmed_qty(self):
		item = SimpleNamespace(precision=lambda field: 0)
		self.assertEqual(schedule_collaboration.validate_sales_final_quantity(4000, 5000, item, 10000),
			service.Decimal(4000))

	def test_sales_final_qty_cannot_exceed_logistics_confirmed_qty(self):
		item = SimpleNamespace(precision=lambda field: 0)
		with patch.object(schedule_collaboration, "_", side_effect=lambda message: message), \
			patch.object(frappe, "throw", side_effect=lambda message, exc=frappe.ValidationError: (_ for _ in ()).throw(exc(message))):
			with self.assertRaisesRegex(frappe.ValidationError, "cannot exceed Logistics Confirmed"):
				schedule_collaboration.validate_sales_final_quantity(6000, 5000, item, 10000)

	def test_sales_cannot_rebalance_a_logistics_confirmed_schedule(self):
		schedule = frappe._dict(name="SCHED-1", logistics_confirmed_by="logistics@example.com",
			confirmation_status="In Review")
		db = SimpleNamespace(exists=Mock(return_value=False))
		with patch.object(service, "_", side_effect=lambda message: message), \
			patch.object(service.frappe, "throw", side_effect=lambda message, exc=frappe.ValidationError: (_ for _ in ()).throw(exc(message))), \
			patch.object(service.frappe, "db", db):
			with self.assertRaisesRegex(frappe.ValidationError, "Logistics owns changes"):
				service._assert_schedule_plan_editable(schedule)

	class FakeMeta:
		fields = {"custom_logistics_reason", "custom_logistics_remarks", "custom_logistics_proposed_date", "custom_logistics_proposed_qty", "custom_sales_final_qty", "custom_sales_move_date", "custom_sales_remove"}
		def has_field(self, fieldname):
			return fieldname in self.fields

	class FakeItem:
		def __init__(self):
			self.qty = 2
			self.meta = TestDeliveryScheduleService.FakeMeta()
			self.values = {"custom_so_delivery_schedule": "SCHED-1"}
			self.so_detail = "SOI-1"
			self.custom_logistics_reason = "OK"
			self.custom_logistics_remarks = "Confirmed"
			self.custom_logistics_proposed_date = "2026-11-13"
			self.custom_logistics_proposed_qty = 2
			self.custom_sales_final_qty = 2
			self.custom_sales_move_date = "2026-11-13"
			self.custom_sales_remove = 0
		def get(self, key):
			return self.values.get(key)
		def set(self, key, value):
			self.values[key] = value
			setattr(self, key, value)

	class FakeDeliveryNote:
		name = "MAT-DN-TEST-1"
		docstatus = 0
		workflow_state = "For Stock Confirmation"
		status = "For Stock Confirmation"
		custom_dr_number = "DR-TEST-1"
		def __init__(self, item):
			self.items = [item]
			self.run_method = Mock()
			self.save = Mock()
			self.add_comment = Mock()

	def test_partial_schedule_allocation_is_added_to_existing_matching_item(self):
		item = self.FakeItem()
		dn = self.FakeDeliveryNote(item)
		packed_item_module = ModuleType("erpnext.stock.doctype.packed_item.packed_item")
		packed_item_module.make_packing_list = Mock()
		with patch.object(service, "_", side_effect=lambda message: message), \
			patch.dict("sys.modules", {"erpnext.stock.doctype.packed_item.packed_item": packed_item_module}):
			service._consolidate_schedule_draft(dn, "SCHED-1", "SOI-1", 3)
		self.assertEqual(item.qty, 5)
		self.assertIsNone(item.custom_logistics_reason)
		self.assertIsNone(item.custom_logistics_remarks)
		self.assertIsNone(item.custom_logistics_proposed_date)
		self.assertEqual(item.custom_logistics_proposed_qty, 0)
		self.assertEqual(item.custom_sales_final_qty, 0)
		self.assertIsNone(item.custom_sales_move_date)
		self.assertEqual(item.custom_sales_remove, 0)
		dn.run_method.assert_called_once_with("calculate_taxes_and_totals")
		packed_item_module.make_packing_list.assert_called_once_with(dn)
		dn.save.assert_called_once_with()
		dn.add_comment.assert_called_once()

	def test_schedule_draft_consolidation_keeps_stock_confirmation_state(self):
		dn = self.FakeDeliveryNote(self.FakeItem())
		with patch.object(service, "_", side_effect=lambda message: message), \
			patch.object(service.frappe, "throw", side_effect=lambda message, exc=frappe.ValidationError: (_ for _ in ()).throw(exc(message))):
			packed_item_module = ModuleType("erpnext.stock.doctype.packed_item.packed_item")
			packed_item_module.make_packing_list = Mock()
			with patch.dict("sys.modules", {"erpnext.stock.doctype.packed_item.packed_item": packed_item_module}):
				service._consolidate_schedule_draft(dn, "SCHED-1", "SOI-1", 1)
		self.assertEqual(dn.workflow_state, "For Stock Confirmation")
		self.assertEqual(dn.status, "For Stock Confirmation")
		self.assertEqual(dn.custom_dr_number, "DR-TEST-1")
		dn.save.assert_called_once_with()

	def test_schedule_draft_consolidation_rejects_sales_finalized_delivery_note(self):
		dn = self.FakeDeliveryNote(self.FakeItem())
		dn.workflow_state = "For DR Printing"
		with patch.object(service, "_", side_effect=lambda message: message):
			with patch.object(service.frappe, "throw", side_effect=lambda message, exc=frappe.ValidationError: (_ for _ in ()).throw(exc(message))):
				with self.assertRaisesRegex(frappe.ValidationError, "finalized by Sales"):
					service._consolidate_schedule_draft(dn, "SCHED-1", "SOI-1", 1)
		dn.save.assert_not_called()

	def test_schedule_draft_consolidation_rejects_delivery_submitted_for_delivery(self):
		dn = self.FakeDeliveryNote(self.FakeItem())
		dn.workflow_state = "To Deliver and Bill"
		with patch.object(service, "_", side_effect=lambda message: message):
			with patch.object(service.frappe, "throw", side_effect=lambda message, exc=frappe.ValidationError: (_ for _ in ()).throw(exc(message))):
				with self.assertRaisesRegex(frappe.ValidationError, "finalized by Sales or submitted for delivery"):
					service._consolidate_schedule_draft(dn, "SCHED-1", "SOI-1", 3)
		dn.save.assert_not_called()

	def test_multi_item_draft_payload_preserves_each_schedule_reference(self):
		class BaseItem:
			def __init__(self, so_detail, item_code):
				self.so_detail = so_detail
				self.values = {"so_detail": so_detail, "item_code": item_code, "qty": 99,
					"name": "MAPPER-ROW", "parent": "SO-1", "parentfield": "items", "idx": 1}
			def as_dict(self):
				return dict(self.values)

		entries = [
			(SimpleNamespace(name="SCHED-1"), SimpleNamespace(name="SOI-1"), 3),
			(SimpleNamespace(name="SCHED-2"), SimpleNamespace(name="SOI-1"), 2),
			(SimpleNamespace(name="SCHED-3"), SimpleNamespace(name="SOI-2"), 4),
		]
		payloads = service._delivery_note_schedule_item_payloads(
			[BaseItem("SOI-1", "ITEM-1"), BaseItem("SOI-2", "ITEM-2")], entries)
		self.assertEqual(len(payloads), 3)
		self.assertEqual([(row["so_detail"], row["qty"], row[service.DN_SCHEDULE_FIELD])
			for row in payloads], [("SOI-1", 3.0, "SCHED-1"), ("SOI-1", 2.0, "SCHED-2"),
			("SOI-2", 4.0, "SCHED-3")])
		self.assertTrue(all("name" not in row and "parent" not in row for row in payloads))

	def test_multi_item_draft_payload_rejects_missing_mapper_item(self):
		class BaseItem:
			so_detail = "SOI-1"
			def as_dict(self):
				return {"so_detail": self.so_detail}

		with patch.object(service, "_", side_effect=lambda message: message), \
			patch.object(service.frappe, "throw", side_effect=lambda message, exc=frappe.ValidationError: (_ for _ in ()).throw(exc(message))):
			with self.assertRaisesRegex(frappe.ValidationError, "could not map Sales Order Item"):
				service._delivery_note_schedule_item_payloads(
					[BaseItem()], [(SimpleNamespace(name="SCHED-2"), SimpleNamespace(name="SOI-2"), 1)])

	def test_multi_item_dn_compatibility_requires_same_so_date_and_warehouse(self):
		so = SimpleNamespace(name="SO-1")
		item_a = SimpleNamespace(warehouse="FG - Guyong")
		item_b = SimpleNamespace(warehouse="FG - Guyong")
		item_other_warehouse = SimpleNamespace(warehouse="Stores - QC")
		date = SimpleNamespace(delivery_date="2026-11-21")
		other_date = SimpleNamespace(delivery_date="2026-11-22")
		self.assertEqual(service._delivery_note_compatibility_key(so, date, item_a),
			service._delivery_note_compatibility_key(so, date, item_b))
		self.assertNotEqual(service._delivery_note_compatibility_key(so, date, item_a),
			service._delivery_note_compatibility_key(so, other_date, item_b))
		self.assertNotEqual(service._delivery_note_compatibility_key(so, date, item_a),
			service._delivery_note_compatibility_key(so, date, item_other_warehouse))

	def test_schedule_with_submitted_delivery_note_cannot_create_a_second(self):
		linked = [frappe._dict(name="MAT-DN-1", docstatus=1)]
		with patch.object(service, "_", side_effect=lambda message: message), \
			patch.object(service.frappe, "throw", side_effect=lambda message, exc=frappe.ValidationError: (_ for _ in ()).throw(exc(message))):
			with self.assertRaisesRegex(frappe.ValidationError, "Create a separate schedule"):
				service._validate_no_submitted_schedule_delivery(linked, "SCHED-1")

	def test_unscheduled_balance_is_derived(self):
		self.assertEqual(service.derived_unplanned_qty("100.000", "25.000", "60.000"), 15)

	def test_submitted_delivery_reduces_demand_without_double_counting(self):
		# Linked fulfillment remains inside scheduled Total instead of reducing it again.
		self.assertEqual(service.derived_unplanned_qty(100, 100, 100, 100), 0)
		self.assertEqual(service.derived_unplanned_qty(100, 30, 70), 0)

	def test_planned_quantity_cannot_exceed_remaining_demand(self):
		with patch.object(service, "_", side_effect=lambda message: message), patch.object(service.frappe, "throw", side_effect=lambda message, exc=frappe.ValidationError: (_ for _ in ()).throw(exc(message))):
			with self.assertRaisesRegex(frappe.ValidationError, "exceed"):
				service.derived_unplanned_qty(100, 30, 71)

	def test_negative_planned_quantity_is_rejected(self):
		with patch.object(service, "_", side_effect=lambda message: message), patch.object(service.frappe, "throw", side_effect=lambda message, exc=frappe.ValidationError: (_ for _ in ()).throw(exc(message))):
			with self.assertRaises(frappe.ValidationError):
				service.derived_unplanned_qty(100, 0, -1)

	def test_sales_scheduling_query_reads_only_schedule_ledger_without_version_flag(self):
		row = frappe._dict(schedule_id="SCHED-1", so_detail="SOI-1",
			sales_order="SO-1", customer_name="Test Customer", so_type="REGULAR", item_code="ITEM-1",
			item_name="Test Item", warehouse="Main", qty=8, uom="Nos", delivered_qty=0, balance_qty=10,
			draft_dr_qty=2, available_qty=6, actual_qty=20, delivery_date="2026-11-12", available_from="2026-11-12",
			history_status="Verified")
		mock_sql = Mock(side_effect=[[row], [[2]]])
		fake_db = type("DatabaseStub", (), {"sql": mock_sql})()
		with patch.object(scheduling_report, "_", side_effect=lambda message: message), \
			patch.object(scheduling_report, "_is_sales_coordinator", return_value=False), \
			patch.dict(scheduling_report.frappe.__dict__, {"db": fake_db}):
			_, rows, _, _, _ = scheduling_report.execute({"company": "_Test Company", "delivery_date": "2026-11-12"})
		self.assertEqual([row.schedule_id for row in rows], ["SCHED-1"])
		queries = [call.args[0] for call in mock_sql.call_args_list]
		self.assertIn("FROM `tabSO Delivery Schedule` s", queries[0])
		self.assertNotIn("custom_delivery_schedule_v2_enabled", queries[0])
		self.assertNotIn("UNSCHEDULED:", queries[0])


class TestCancelledScheduleReplacement(TestCase):
	def setUp(self):
		self.source = SimpleNamespace(
			name="SCHED-OLD", modified="v2", sales_order="SO-TEST", sales_order_item="SOI-TEST",
			item_code="ITEM-TEST", warehouse="WH-TEST", delivery_date="2026-11-12",
			planned_qty=3, final_qty=3, confirmation_status="Finalized", remarks="Original plan",
			history_status="Verified", current_total=3, original_promise_date="2026-11-12",
			save=Mock(),
		)
		self.replacement = SimpleNamespace(name="SCHED-NEW", insert=Mock())
		self.sales_order = SimpleNamespace(
			name="SO-TEST", docstatus=1, status="To Deliver and Bill", custom_so_type="REGULAR",
			transaction_date="2026-11-01", get=lambda field: None,
		)
		self.item = SimpleNamespace(
			name="SOI-TEST", item_code="ITEM-TEST", warehouse="WH-TEST", uom="Nos",
			conversion_factor=1, precision=lambda field: 3,
		)
		self.history = [frappe._dict(delivery_note="DN-CANCELLED", docstatus=2,
			dn_detail="DNI-CANCELLED", qty=3)]
		self.sql = Mock(side_effect=[[], self.history, []])
		self.db = SimpleNamespace(
			get_value=Mock(return_value=frappe._dict(sales_order_item="SOI-TEST", sales_order="SO-TEST")),
			sql=self.sql, exists=Mock(return_value=False), savepoint=Mock(), rollback=Mock(),
		)
		self.flags = frappe._dict()
		self.get_doc = Mock(side_effect=lambda value, *args, **kwargs:
			self.replacement if isinstance(value, dict) else self.source)
		def fail(message, exc=frappe.ValidationError, **kwargs):
			raise exc(message)
		for patcher in (
			patch.object(frappe, "db", self.db),
			patch.object(frappe, "flags", self.flags),
			patch.object(frappe, "session", frappe._dict(user="sales@example.test")),
			patch.object(frappe, "get_roles", return_value=["Sales Coordinator"]),
			patch.object(frappe, "get_doc", self.get_doc),
			patch.object(frappe, "get_all", return_value=[]),
			patch.object(frappe, "throw", side_effect=fail),
			patch.object(service, "_", side_effect=lambda message: message),
			patch.object(service, "flt", side_effect=lambda value, precision=None: round(float(value), precision) if precision is not None else float(value)),
			patch.object(service, "_load_so_item", return_value=(self.sales_order, self.item)),
			patch.object(service, "_require_sales_access"),
		):
			patcher.start()
			self.addCleanup(patcher.stop)

	def test_cancelled_demand_moves_to_new_pending_schedule(self):
		with patch.object(service, "_transfer_to_new_schedule", return_value=(self.replacement, "tx-1")) as transfer:
			result = service.authorize_cancelled_schedule_replacement(
				"SCHED-OLD", "2026-11-20", "Customer requested a revised date", "v2")
		self.assertEqual(result, {"source": "SCHED-OLD", "replacement": "SCHED-NEW",
			"quantity": 3.0, "delivery_date": "2026-11-20", "transaction_id": "tx-1"})
		self.assertEqual(self.source.planned_qty, 3)
		self.assertEqual(self.source.remarks, "Original plan")
		transfer.assert_called_once()
		self.assertEqual(transfer.call_args.args[3], 3)
		self.assertEqual(transfer.call_args.args[4], "2026-11-20")
		self.assertEqual(transfer.call_args.kwargs["allow_protected"], True)
		self.assertIsNone(self.flags.delivery_schedule_service_write)

	def test_replacement_rejects_non_cancelled_delivery_note_history(self):
		self.history[0].docstatus = 0
		with self.assertRaisesRegex(frappe.ValidationError, "every linked Delivery Note is canceled"):
			service.authorize_cancelled_schedule_replacement(
				"SCHED-OLD", "2026-11-20", "Approved", "v2")
		self.source.save.assert_not_called()
		self.replacement.insert.assert_not_called()


class TestScheduleMovementHelpers(TestCase):
	def test_logistics_reconciliation_uses_scoped_non_sales_quantity_read(self):
		with patch.object(service, "quantity_state", return_value={"precision": 0}) as quantity_state:
			result = service._get_logistics_reconciliation_quantity_state("SOI-LOGISTICS")
		self.assertEqual(result, {"precision": 0})
		quantity_state.assert_called_once_with(
			"SOI-LOGISTICS", lock=True, check_sales_access=False
		)

	def setUp(self):
		self.flags = frappe._dict()
		self.db = SimpleNamespace(savepoint=Mock(), rollback=Mock(), get_value=Mock())
		self.source = frappe._dict(name="SCHED-SOURCE", sales_order="SO-1", sales_order_item="SOI-1",
			item_code="ITEM-1", warehouse="WH-1", delivery_date="2026-11-14", planned_qty=10,
			current_total=10, original_qty=10, quantity_changes=0, original_promise_date="2026-11-14",
			history_status="Verified", remarks="Human-entered source note", modified="v1", uom="PC",
			conversion_factor=1, save=Mock(), reload=Mock())
		self.item = SimpleNamespace(name="SOI-1", item_code="ITEM-1", warehouse="WH-1", uom="PC",
			conversion_factor=1, precision=lambda field: 0)
		self.so = SimpleNamespace(name="SO-1", transaction_date="2026-11-01")

	def test_negative_quantity_adjustment_preserves_origin_and_appends_promise_attribution(self):
		self.db.get_value.side_effect = ["SOI-1", None]
		with patch.object(frappe, "db", self.db), patch.object(frappe, "flags", self.flags), \
			patch.object(frappe, "get_doc", return_value=self.item), \
			patch.object(service, "quantity_state", return_value={"available_scheduled_qty": {"SCHED-SOURCE": 4}}), \
			patch.object(service, "_allocate_promise_attributions", return_value=[("SCHED-SOURCE", "2026-11-14", service.Decimal(2))]), \
			patch.object(service, "_clear_schedule_confirmation"), \
			patch.object(service, "append_schedule_movement") as append, \
			patch.object(service, "_", side_effect=lambda text: text):
			service._adjust_schedule_total(self.source, 8, "Sales removed two pieces", idempotency_key="adjust-1")
		self.assertEqual(self.source.planned_qty, 8)
		self.assertEqual(self.source.remarks, "Human-entered source note")
		self.assertEqual(self.source.original_qty, 10)
		self.assertEqual(self.source.original_promise_date, "2026-11-14")
		movement = append.call_args.kwargs
		self.assertEqual(movement["operation_type"], "Quantity Adjustment")
		self.assertEqual(movement["source_schedule"], "SCHED-SOURCE")
		self.assertEqual(movement["promise_commitment"], "SCHED-SOURCE")
		self.assertEqual(movement["promise_qty"], 2)

	def test_transfer_creates_new_provenance_row_and_does_not_overwrite_source_remarks(self):
		destination = SimpleNamespace(name="SCHED-DEST", current_total=5, planned_qty=5,
			insert=Mock(), history_status="Verified")
		self.db.get_value.return_value = None
		with patch.object(frappe, "db", self.db), patch.object(frappe, "flags", self.flags), \
			patch.object(frappe, "get_doc", return_value=destination), \
			patch.object(service, "quantity_state", return_value={"available_scheduled_qty": {"SCHED-SOURCE": 5}}), \
			patch.object(service, "_allocate_promise_attributions", return_value=[("SCHED-SOURCE", "2026-11-14", service.Decimal(5))]), \
			patch.object(service, "_has_protected_schedule_delivery", return_value=False), \
			patch.object(service, "_clear_schedule_confirmation"), \
			patch.object(service, "append_schedule_movement") as append, \
			patch.object(service, "_", side_effect=lambda text: text):
			created, transaction_id = service._transfer_to_new_schedule(self.source, self.so, self.item,
				5, "2026-11-16", "Move five pieces", idempotency_key="transfer-1")
		self.assertIs(created, destination)
		self.assertEqual(transaction_id, "transfer-1")
		self.assertEqual(self.source.planned_qty, 5)
		self.assertEqual(self.source.remarks, "Human-entered source note")
		self.assertEqual(self.source.original_qty, 10)
		self.assertEqual(append.call_count, 2)
		self.assertEqual({call.kwargs["operation_type"] for call in append.call_args_list}, {"Transfer Out", "Transfer In"})
		for movement in append.call_args_list:
			self.assertEqual(movement.kwargs["promise_commitment"], "SCHED-SOURCE")
			self.assertEqual(movement.kwargs["destination_schedule"], "SCHED-DEST")
		self.assertEqual(movement.kwargs["transaction_id"], "transfer-1")


class TestCancelledScheduleReplacementRemaining(TestCancelledScheduleReplacement):
	def test_replacement_rejects_quantity_that_does_not_reconcile(self):
		self.history[0].qty = 2
		with self.assertRaisesRegex(frappe.ValidationError, "does not match canceled Delivery Note history"):
			service.authorize_cancelled_schedule_replacement(
				"SCHED-OLD", "2026-11-20", "Approved", "v2")
		self.source.save.assert_not_called()
		self.replacement.insert.assert_not_called()

	def test_replacement_rejects_an_active_sales_invoice(self):
		with patch.object(frappe, "get_all", side_effect=[["SI-1"], ["SI-1"]]):
			with self.assertRaisesRegex(frappe.ValidationError, "Sales Invoice is still active"):
				service.authorize_cancelled_schedule_replacement(
					"SCHED-OLD", "2026-11-20", "Approved", "v2")
		self.source.save.assert_not_called()
		self.replacement.insert.assert_not_called()
