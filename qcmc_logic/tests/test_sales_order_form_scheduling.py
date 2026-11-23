"""Site-free checks for form scheduling authorization and lifecycle boundaries."""

from unittest import TestCase
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, call, patch

import frappe

from qcmc_logic.api import delivery_schedule_service as service
from qcmc_logic.api import sales_order_schedule_split as legacy_split
from qcmc_logic.api import sales_order_delivery_eligibility as eligibility
from qcmc_logic.api import delivery_schedule_collaboration_v2 as collaboration


class TestSalesOrderFormScheduling(TestCase):
	def test_delivery_eligibility_accepts_partial_fulfillment_statuses_only(self):
		for status in eligibility.OPEN_DELIVERY_STATUSES:
			with self.subTest(status=status):
				so = frappe._dict(docstatus=1, status=status, is_return=0)
				self.assertTrue(eligibility.is_open_sales_order_for_delivery(so))
		for status in ("Draft", "On Hold", "To Pay", "Completed", "Closed", "Cancelled"):
			with self.subTest(status=status):
				so = frappe._dict(docstatus=1, status=status, is_return=0)
				self.assertFalse(eligibility.is_open_sales_order_for_delivery(so))
		self.assertFalse(eligibility.is_open_sales_order_for_delivery(
			frappe._dict(docstatus=1, status="To Deliver", is_return=1)))

	def test_initial_baselines_use_item_date_then_parent_date_and_outstanding_qty(self):
		so = SimpleNamespace(delivery_date="2026-11-30", items=[
			frappe._dict(name="SOI-1", item_code="ITEM-1", qty=10, delivered_qty=2,
				delivery_date="2026-11-21", precision=lambda field: 2),
			frappe._dict(name="SOI-2", item_code="ITEM-2", qty=5, delivered_qty=0,
				delivery_date=None, precision=lambda field: 2),
			frappe._dict(name="SOI-3", item_code="ITEM-3", qty=3, delivered_qty=0,
				delivery_date="2026-11-22", precision=lambda field: 2),
		])
		with patch.object(service, "flt", side_effect=lambda value, precision=None: round(float(value or 0), precision) if precision is not None else float(value or 0)):
			entries = service._baseline_schedule_entries(so, {"SOI-3"}, {"SOI-1": 1})
		self.assertEqual([(e["item"].name, str(e["delivery_date"]), e["planned_qty"]) for e in entries], [
			("SOI-1", "2026-11-21", service.Decimal("7.0")),
			("SOI-2", "2026-11-30", service.Decimal("5.0")),
		])

	def test_baseline_without_any_delivery_date_is_rejected(self):
		so = SimpleNamespace(delivery_date=None, items=[SimpleNamespace(name="SOI-1", item_code="ITEM-1",
			qty=1, delivered_qty=0, delivery_date=None, precision=lambda field: 2)])
		with patch.object(service, "flt", side_effect=lambda value, precision=None: float(value or 0)), \
			patch.object(service, "_", side_effect=lambda text, *args: text.format(*args) if args else text), \
			patch.object(frappe, "throw", side_effect=lambda message, exc=frappe.ValidationError: (_ for _ in ()).throw(exc(message))):
			with self.assertRaisesRegex(frappe.ValidationError, "Set a Delivery Date"):
				service._baseline_schedule_entries(so, set(), {})

	def test_proceed_preview_preserves_selection_and_reports_same_date_omissions(self):
		so = SimpleNamespace(name="SO-1", customer_name="Customer", company="Company")
		item_a = SimpleNamespace(name="SOI-1", item_code="ITEM-1", item_name="One", uom="Nos", warehouse="WH-1",
			precision=lambda field: 2)
		item_b = SimpleNamespace(name="SOI-2", item_code="ITEM-2", item_name="Two", uom="Nos", warehouse="WH-1",
			precision=lambda field: 2)
		rows = {
		"SCHED-1": SimpleNamespace(name="SCHED-1", modified="m1", planned_qty=4, confirmation_status="In Review",
			sales_confirmed_by=None, logistics_confirmed_by="logistics", logistics_committed_qty=4,
			final_qty=None, delivery_date="2026-11-30"),
		"SCHED-2": SimpleNamespace(name="SCHED-2", modified="m2", planned_qty=2, confirmation_status="Finalized",
			sales_confirmed_by="sales", logistics_confirmed_by="logistics", logistics_committed_qty=2,
			final_qty=2, delivery_date="2026-11-30"),
		}
		items = {"SCHED-1": item_a, "SCHED-2": item_b}
		states = {name: {"draft_allocated_by_schedule": {name: 1}, "available_scheduled_qty": {name: 5}}
			for name in rows}
		candidates = [SimpleNamespace(name="SCHED-2", sales_order_item="SOI-2", modified="m2", final_qty=2)]
		with patch.object(collaboration, "_require_role"), \
			patch.object(collaboration, "_load_locked", side_effect=lambda name, modified, department: (rows[name], so, items[name])), \
			patch.object(collaboration, "flt", side_effect=lambda value, precision=None: float(value or 0)):
			with patch.object(service, "quantity_state", side_effect=lambda item: states["SCHED-1" if item == "SOI-1" else "SCHED-2"]), \
				patch.object(collaboration.frappe, "get_all", return_value=candidates), \
				patch.object(collaboration.frappe, "db", SimpleNamespace(sql=Mock(return_value=[]))):
				preview = collaboration.get_proceed_to_dr_preview([
					{"schedule": "SCHED-1", "modified": "m1", "draft_allocated_qty": 1}])
		self.assertEqual([row["schedule"] for row in preview["schedules"]], ["SCHED-1"])
		self.assertEqual(preview["groups"][0]["items"][0]["final_qty"], 4)
		self.assertEqual(preview["groups"][0]["items"][0]["qty_to_add"], 3)
		self.assertEqual([row["schedule"] for row in preview["omitted"]], ["SCHED-2"])

	def test_one_sales_order_grid_flattens_all_items_and_keeps_per_row_remarks(self):
		so = SimpleNamespace(name="SO-1", docstatus=0, modified="2026-11-12 09:00:00", items=[
			frappe._dict(name="SOI-1", idx=1, item_code="ITEM-1", item_name="Item 1", uom="Nos", qty=10, delivered_qty=2),
			frappe._dict(name="SOI-2", idx=2, item_code="ITEM-2", item_name="Item 2", uom="Nos", qty=4, delivered_qty=1),
		], get=lambda key: 0)
		states = {
			"SOI-1": {"state": "state-1", "ordered_qty": 10, "delivered_qty": 2, "precision": 3, "rows": [
				{"name": "SCHED-1", "delivery_date": "2026-11-13", "planned_qty": 2, "allocated_qty": 1,
					"editable_qty": 1, "has_dn_history": True, "date_locked": False, "remarks": "First reason"},
				{"name": "SCHED-2", "delivery_date": "2026-11-14", "planned_qty": 3, "allocated_qty": 0,
					"editable_qty": 3, "has_dn_history": False, "date_locked": False, "remarks": "Second reason"},
			]},
			"SOI-2": {"state": "state-2", "ordered_qty": 4, "delivered_qty": 1, "precision": 3, "rows": []},
		}
		with patch.object(service, "_require_sales_access"), \
			patch.object(service, "get_form_schedule_state", side_effect=lambda so_name, item_name: states[item_name]), \
			patch.object(service.frappe, "as_json", side_effect=lambda value: str(value)), \
			patch.object(service, "flt", side_effect=lambda value, precision=None: float(value or 0)):
			grid = service._get_sales_order_schedule_grid(so)
		self.assertEqual(len(grid["items"]), 2)
		self.assertEqual(len(grid["rows"]), 2)
		item_one_rows = [row for row in grid["rows"] if row["sales_order_item"] == "SOI-1"]
		self.assertEqual([row["remarks"] for row in item_one_rows], ["First reason", "Second reason"])
		self.assertEqual([row["total_scheduled_qty"] for row in item_one_rows], [5, 5])
		self.assertEqual([row["total_committed_qty"] for row in item_one_rows], [1, 1])
		self.assertEqual([row["unscheduled_qty"] for row in item_one_rows], [3, 3])
		self.assertNotIn("SOI-2", [row["sales_order_item"] for row in grid["rows"]])
		item_two = next(item for item in grid["items"] if item["sales_order_item"] == "SOI-2")
		self.assertEqual(item_two["remaining_qty"], 3)

	def test_combined_save_groups_rows_by_item_and_preserves_per_row_remarks(self):
		so = SimpleNamespace(name="SO-1", items=[frappe._dict(name="SOI-1"), frappe._dict(name="SOI-2")])
		grid = {"state": "expected", "item_states": {"SOI-1": "item-state-1", "SOI-2": "item-state-2"}}
		db = MagicMock()
		db.get_value.return_value = "SO-1"
		entries = [
			{"sales_order_item": "SOI-1", "schedule_name": "SCHED-1", "delivery_date": "2026-11-13", "planned_qty": 2, "remarks": "First"},
			{"sales_order_item": "SOI-2", "schedule_name": "SCHED-2", "delivery_date": "2026-11-14", "planned_qty": 3, "remarks": "Second"},
		]
		with patch.object(service, "_get_sales_order_schedule_grid", side_effect=[grid, grid]), \
			patch.object(service, "_lock_schedules") as lock_schedules, \
			patch.object(service, "save_form_schedule_plan") as save_item, \
			patch.object(service.frappe, "db", db), \
			patch.object(service.frappe, "get_doc", return_value=so):
			service.save_sales_order_schedule_grid("SO-1", entries, "expected")
		self.assertEqual(lock_schedules.call_args_list, [call("SOI-1"), call("SOI-2")])
		self.assertEqual(save_item.call_args_list, [
			call("SO-1", "SOI-1", [{"name": "SCHED-1", "delivery_date": "2026-11-13", "planned_qty": 2, "remarks": "First"}], "item-state-1"),
			call("SO-1", "SOI-2", [{"name": "SCHED-2", "delivery_date": "2026-11-14", "planned_qty": 3, "remarks": "Second"}], "item-state-2"),
		])
		db.savepoint.assert_called_once_with("save_sales_order_schedule_grid")

	def test_zero_planned_quantity_is_rejected_by_the_service(self):
		with patch.object(service, "_", side_effect=lambda text: text), \
			patch.object(frappe, "throw", side_effect=lambda message, exc=frappe.ValidationError: (_ for _ in ()).throw(exc(message))):
			with self.assertRaisesRegex(frappe.ValidationError, "greater than zero"):
				service._schedule_plan_quantity("0", 3)

	def test_partially_committed_date_move_keeps_dn_quantity_and_transfers_only_free_balance(self):
		row = frappe._dict(name="SCHED-1", delivery_date="2026-11-13", planned_qty=5, remarks="Original reason", history_status="Verified")
		snapshot = {"rows": [row], "allocated": {"SCHED-1": 2},
			"has_history": {"SCHED-1": True}, "locked_date": {"SCHED-1": False}}
		clean = [{"name": "SCHED-1", "delivery_date": "2026-11-15", "planned_qty": service.Decimal("5"), "remarks": "Move free part"}]
		operations, new_by_date, _ = service._build_form_schedule_operations(clean, snapshot)
		self.assertEqual(operations, [("transfer", row, "2026-11-15", service.Decimal("3"), "Move free part")])
		self.assertEqual(new_by_date, [])

	def test_fully_committed_schedule_cannot_be_moved(self):
		row = frappe._dict(name="SCHED-1", delivery_date="2026-11-13", planned_qty=2, remarks="Reason", history_status="Verified")
		snapshot = {"rows": [row], "allocated": {"SCHED-1": 2},
			"has_history": {"SCHED-1": True}, "locked_date": {"SCHED-1": False}}
		clean = [{"name": "SCHED-1", "delivery_date": "2026-11-15", "planned_qty": service.Decimal("2"), "remarks": "Reason"}]
		with patch.object(service, "_", side_effect=lambda text: text), \
			patch.object(frappe, "throw", side_effect=lambda message, exc=frappe.ValidationError: (_ for _ in ()).throw(exc(message))):
			with self.assertRaisesRegex(frappe.ValidationError, "no free quantity"):
				service._build_form_schedule_operations(clean, snapshot)

	def test_submitted_dn_history_locks_schedule_date(self):
		row = frappe._dict(name="SCHED-1", delivery_date="2026-11-13", planned_qty=3, remarks="Reason", history_status="Verified")
		snapshot = {"rows": [row], "allocated": {},
			"has_history": {"SCHED-1": True}, "locked_date": {"SCHED-1": True}}
		clean = [{"name": "SCHED-1", "delivery_date": "2026-11-15", "planned_qty": service.Decimal("3"), "remarks": "Reason"}]
		with patch.object(service, "_", side_effect=lambda text: text), \
			patch.object(frappe, "throw", side_effect=lambda message, exc=frappe.ValidationError: (_ for _ in ()).throw(exc(message))):
			with self.assertRaisesRegex(frappe.ValidationError, "date is locked"):
				service._build_form_schedule_operations(clean, snapshot)

	def test_removing_partially_committed_row_preserves_only_committed_balance(self):
		row = frappe._dict(name="SCHED-1", delivery_date="2026-11-13", planned_qty=5, remarks="Reason", history_status="Verified")
		snapshot = {"rows": [row], "allocated": {"SCHED-1": 2},
			"has_history": {"SCHED-1": True}, "locked_date": {"SCHED-1": False}}
		operations, new_by_date, _ = service._build_form_schedule_operations([], snapshot)
		self.assertEqual(operations, [("adjust", row, "2026-11-13", service.Decimal("2"), "Reason")])
		self.assertEqual(new_by_date, [])

	def test_removing_unallocated_schedule_zeroes_it_without_deleting_history(self):
		row = frappe._dict(name="SCHED-1", delivery_date="2026-11-13", planned_qty=5, remarks="Reason", history_status="Verified")
		snapshot = {"rows": [row], "allocated": {}, "has_history": {}, "locked_date": {}}
		operations, new_by_date, _ = service._build_form_schedule_operations([], snapshot)
		self.assertEqual(operations, [("adjust", row, "2026-11-13", service.Decimal(0), "Reason")])
		self.assertEqual(new_by_date, [])

	def test_legacy_rebalance_requires_sales_order_write_permission(self):
		with patch.object(legacy_split, "_", side_effect=lambda text: text), \
			patch.object(frappe, "throw", side_effect=lambda message, exc=frappe.ValidationError: (_ for _ in ()).throw(exc(message))):
			with self.assertRaisesRegex(frappe.ValidationError, "retired"):
				legacy_split._load_source("SOI-1")

	def test_submitted_so_26_00038_can_open_shared_schedule_service_without_flag(self):
		item = frappe._dict(name="SOI-1", item_code="ITEM-1", warehouse="FG", qty=5)
		for status, docstatus in (("Draft", 0), ("To Deliver and Bill", 1)):
			with self.subTest(status=status):
				so = SimpleNamespace(name="26-00038", docstatus=docstatus, status=status,
					custom_so_type="REGULAR", company="Company", delivery_date="2026-11-30",
					get=lambda field: None)
			fake_frappe = SimpleNamespace(db=SimpleNamespace(get_value=Mock(side_effect=[0, "Company"])))
			with patch.object(service, "frappe", fake_frappe):
				service._validate_form_schedule_eligibility(so, item)

	def test_baseline_initialization_skips_existing_unreconciled_item(self):
		so = SimpleNamespace(delivery_date="2026-11-30", items=[frappe._dict(name="SOI-1",
			item_code="ITEM-1", qty=5, delivered_qty=0, delivery_date="2026-11-21",
			precision=lambda field: 2)])
		with patch.object(service, "flt", side_effect=lambda value, precision=None: float(value or 0)):
			entries = service._baseline_schedule_entries(so, {"SOI-1"}, {})
		self.assertEqual(entries, [])

	def test_missing_item_baseline_initializes_once_on_repeated_calls(self):
		item = frappe._dict(name="SOI-1", item_code="ITEM-1", warehouse="WH-1", qty=5,
			delivered_qty=0, delivery_date="2026-11-21", uom="Nos", conversion_factor=1,
			precision=lambda field: 2)
		so = SimpleNamespace(name="26-00038", docstatus=1, status="To Deliver and Bill",
			custom_so_type="REGULAR", company="Company", delivery_date=None, items=[item],
			get=lambda field: None)
		db = SimpleNamespace(get_value=Mock(return_value="26-00038"),
			sql=Mock(side_effect=[None, [], None, []]), savepoint=Mock(), rollback=Mock())
		created_doc = SimpleNamespace(name="SCHED-1", insert=Mock())
		fake_frappe = SimpleNamespace(db=db, flags=frappe._dict(), get_doc=Mock(side_effect=[so, created_doc, so]),
			get_all=Mock(side_effect=[[], [frappe._dict(name="SCHED-1", sales_order_item="SOI-1",
				history_status="Verified")]]))
		with patch.object(service, "frappe", fake_frappe), \
			patch.object(service, "_require_sales_access"), \
			patch.object(service, "_validate_form_schedule_eligibility"), \
			patch.object(service, "_lock_schedules"), \
			patch.object(service, "_", side_effect=lambda text: text), \
			patch.object(service, "flt", side_effect=lambda value, precision=None: round(float(value or 0), precision) if precision is not None else float(value or 0)):
			first = service.initialize_sales_order_delivery_schedules("26-00038")
			second = service.initialize_sales_order_delivery_schedules("26-00038")
		self.assertEqual(first["created_count"], 1)
		self.assertEqual(second["created_count"], 0)
		created_doc.insert.assert_called_once_with(ignore_permissions=True)

	def test_unreconciled_schedule_cannot_be_changed_or_removed(self):
		row = frappe._dict(name="SCHED-OLD", delivery_date="2026-11-13", planned_qty=5,
			remarks="Historical", history_status="Unreconciled")
		snapshot = {"rows": [row], "allocated": {}, "has_history": {}, "locked_date": {}}
		unchanged = [{"name": "SCHED-OLD", "delivery_date": "2026-11-13",
			"planned_qty": service.Decimal("5"), "remarks": "Historical"}]
		with patch.object(service, "_", side_effect=lambda text: text), \
			patch.object(frappe, "throw", side_effect=lambda message, exc=frappe.ValidationError: (_ for _ in ()).throw(exc(message))):
			self.assertEqual(service._build_form_schedule_operations(unchanged, snapshot), ([], [], {"SCHED-OLD"}))
			for entries in ([], [{**unchanged[0], "planned_qty": service.Decimal("4")}]):
				with self.assertRaisesRegex(frappe.ValidationError, "reconciliation"):
					service._build_form_schedule_operations(entries, snapshot)

	def test_saved_plan_blocks_draft_item_quantity_below_schedule(self):
		item = frappe._dict(name="SOI-1", item_code="ITEM-1", qty=4, delivered_qty=0,
			precision=lambda field: 3)
		doc = SimpleNamespace(name="SO-1", docstatus=0, items=[item], set=MagicMock())
		with patch.object(frappe, "get_all", return_value=[frappe._dict(
			name="SCHED-1", sales_order_item="SOI-1", planned_qty=5)]), \
			patch.object(service, "_", side_effect=lambda text: text), \
			patch.object(service, "flt", side_effect=lambda value, precision=None: float(value or 0)), \
			patch.object(frappe, "throw", side_effect=lambda message, exc=frappe.ValidationError: (_ for _ in ()).throw(exc(message))):
			with self.assertRaisesRegex(frappe.ValidationError, "cannot be reduced"):
				service.validate_sales_order_plan(doc, "validate")

	def test_sales_order_plan_validation_does_not_set_an_operational_version_flag(self):
		doc = SimpleNamespace(name="SO-1", docstatus=1, items=[
			frappe._dict(name="SOI-1", item_code="ITEM-1", qty=6, delivered_qty=0, precision=lambda field: 3)
		], set=MagicMock())
		with patch.object(frappe, "get_all", return_value=[frappe._dict(
			name="SCHED-1", sales_order_item="SOI-1", planned_qty=5)]), \
			patch.object(service, "_", side_effect=lambda text: text), \
			patch.object(service, "flt", side_effect=lambda value, precision=None: float(value or 0)):
			service.validate_sales_order_plan(doc, "before_submit")
		doc.set.assert_not_called()

	def test_submitted_dn_cancel_does_not_mutate_schedule_total_but_return_link_is_cleared(self):
		item = frappe._dict(custom_so_delivery_schedule="SCHED-1", qty=2,
			precision=lambda field: 3)
		dn = SimpleNamespace(name="DN-1", items=[item], is_return=0)
		with patch.object(service, "_schedule_delta") as delta, \
			patch.object(service, "flt", side_effect=lambda value, precision=None: float(value or 0)):
			service.on_delivery_note_cancel(dn)
		delta.assert_not_called()

		return_item = SimpleNamespace(custom_so_delivery_schedule="SCHED-1", against_sales_order="SO-1",
			so_detail="SOI-1", item_code="ITEM-1", warehouse="FG", qty=1,
			get=lambda field: getattr(return_item, field, None), set=lambda field, value: setattr(return_item, field, value))
		return_dn = SimpleNamespace(name="RET-1", docstatus=0, is_return=1, items=[return_item])
		with patch.object(service, "flt", side_effect=lambda value, precision=None: float(value or 0)):
			service.validate_delivery_note_item(return_dn)
		self.assertIsNone(return_item.custom_so_delivery_schedule)


if __name__ == "__main__":
	import unittest
	unittest.main()
