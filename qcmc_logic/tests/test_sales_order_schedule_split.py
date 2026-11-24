"""Site-free split tests. No database connection or persisted records."""

from copy import deepcopy
from decimal import Decimal
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch

import frappe

from qcmc_logic.api import sales_order_schedule_split as split


class Record(SimpleNamespace):
	def get(self, field, default=None):
		return getattr(self, field, default)

	def as_dict(self):
		return {key: [row.as_dict() for row in value] if isinstance(value, list) else value
			for key, value in vars(self).items() if not callable(value) and key != "meta"}


class TestScheduleSplit(TestCase):
	def setUp(self):
		self.db = MagicMock()
		self.db.sql.return_value = []
		self.db.get_value.return_value = None
		self.db.exists.return_value = False
		self.meta = MagicMock(fields=[], track_changes=1)
		self.meta.has_field.return_value = False
		self.meta.get_workflow.return_value = None
		self.source = Record(name="SOURCE", parent="SO", item_code="ITEM", warehouse="WH",
			qty=100000, stock_qty=100000, delivered_qty=0, conversion_factor=1,
			uom="Unit", stock_uom="Unit", delivery_date="2026-11-06", rate=5,
			meta=self.meta, precision=lambda field: 3)
		self.so = Record(name="SO", doctype="Sales Order", docstatus=1,
			status="To Deliver and Bill", custom_so_type="REGULAR", transaction_date="2026-11-01",
			modified="2026-11-06 10:00:00", items=[self.source], meta=self.meta,
			check_permission=MagicMock(), precision=lambda field: 3)
		def fail(message, exc=frappe.ValidationError, **kwargs):
			raise exc(message)
		for patcher in (
			patch.object(split, "_", side_effect=lambda value: value),
			patch.object(split, "today", return_value="2026-11-06"),
			patch.object(split.frappe, "throw", side_effect=fail),
			patch.object(split.frappe, "db", self.db),
			patch.object(split.frappe, "get_all", return_value=[]),
			patch.object(split.frappe, "get_system_settings", return_value="Banker's Rounding"),
			patch.object(split.frappe, "logger", return_value=MagicMock()),
			patch.object(split.scheduling, "_validate_sales_coordinator_access"),
			patch.object(split, "_copy_fields", return_value=["item_code", "warehouse", "uom", "stock_uom", "rate", "delivery_date", "conversion_factor"]),
		):
			patcher.start()
			self.addCleanup(patcher.stop)

	def prepare(self, quantity=50000, date="2026-11-09"):
		return split._prepare(self.so, self.source, quantity, date)






















	def test_lock_order_is_deterministic(self):
		split.lock_orders(["SO-B", "SO-A", "SO-B"])
		self.assertEqual([call.args[1] for call in self.db.sql.call_args_list], ["SO-A", "SO-B"])

	def test_dn_allocation_is_rechecked_under_mutex(self):
		doc = Record(name="DN", doctype="Delivery Note", items=[Record(so_detail="SOURCE", qty=50001)], is_new=lambda: True)
		self.db.get_value.return_value = frappe._dict(qty=50000, delivered_qty=0)
		with patch.object(split, "_draft_quantity", return_value=0):
			with self.assertRaises(frappe.ValidationError):
				split._validate_dn_allocation(doc)
		doc.items[0].qty = 50000
		with patch.object(split, "_draft_quantity", return_value=0):
			split._validate_dn_allocation(doc)

	def test_waiting_so_save_rechecks_modified_after_lock(self):
		self.so._original_modified = "old"
		self.so.is_new = lambda: False
		self.so.get_all_children = lambda: []
		self.db.get_value.return_value = "new"
		with self.assertRaises(frappe.TimestampMismatchError):
			split.lock_order_references(self.so)




	def test_standard_child_updater_rechecks_version_under_parent_lock(self):
		self.source.doctype = "Sales Order Item"
		self.source.parenttype = "Sales Order"
		self.source._original_modified = "old"
		self.source.is_new = lambda: False
		self.source.get_all_children = lambda: []
		self.db.get_value.return_value = "new"
		with self.assertRaises(frappe.TimestampMismatchError):
			split.lock_order_references(self.source, "before_update_after_submit")
		self.assertEqual(self.db.sql.call_args.args[1], "SO")
		self.db.get_value.assert_called_with("Sales Order Item", "SOURCE", "modified", for_update=True)



	def add_target(self, qty=30000, rate=5):
		target = deepcopy(self.source)
		target.name = "TARGET"
		target.delivery_date = "2026-11-09"
		target.qty = target.stock_qty = qty
		target.rate = rate
		self.so.items.append(target)
		return target

	def apply_preview(self, preview):
		before = deepcopy(self.so)
		self.so.reload = MagicMock()
		self.so.add_comment = MagicMock(return_value=Record(name="AUDIT"))
		def persist(order):
			for row in order.items:
				row.stock_qty = row.qty * row.conversion_factor
		with patch.object(split, "_load_source", return_value=(self.so, self.source)), patch.object(split.frappe, "get_doc", return_value=before), patch.object(split, "_persist", side_effect=persist):
			return split.split_schedule("SOURCE", preview["move_qty"], "2026-11-09", "Customer request", preview["state"])











	def test_payment_and_tax_snapshots_compare_semantic_values(self):
		from datetime import date
		tax = Record(account_head="VAT", charge_type="On Net Total", rate="12.000", tax_amount="120.00", base_tax_amount="120.00", total="1120.00", base_total="1120.00", precision=lambda field: 2)
		payment = Record(payment_term=None, due_date=date(2026, 11, 7), invoice_portion="100.000", payment_amount="1120.00", base_payment_amount="1120.00", precision=lambda field: 2)
		self.so.taxes = [tax]
		self.so.payment_schedule = [payment]
		before = split._financial_snapshot(self.so)
		payment.payment_term = ""
		payment.due_date = "2026-11-07"
		payment.invoice_portion = 100.0
		payment.payment_amount = payment.base_payment_amount = 1120.0
		for field in ("rate", "tax_amount", "base_tax_amount", "total", "base_total"):
			setattr(tax, field, float(tax.get(field)))
		self.assertEqual(before, split._financial_snapshot(self.so))
		payment.payment_amount = 1100
		changes = split._financial_changes(before, split._financial_snapshot(self.so))
		self.assertTrue(any("Payment amount: 1120.0 → 1100.0" in change for change in changes))

	def test_financial_snapshot_detects_item_amount_drift_independent_of_parent_totals(self):
		self.source.amount = 500000
		self.source.net_amount = 500000
		self.meta.has_field.side_effect = lambda field: field in {"amount", "net_amount"}
		before = split._financial_snapshot(self.so)
		self.source.amount = 499999
		changes = split._financial_changes(before, split._financial_snapshot(self.so))
		self.assertTrue(any("Amount" in change and "499999" in change for change in changes))


	def test_financial_guard_reports_exact_changed_fields(self):
		with patch.object(split, "_financial_snapshot", return_value={"parent": {"grand_total": 1100}, "stock_qty": Decimal("15")}):
			with self.assertRaisesRegex(frappe.ValidationError, "Grand total: 1000.*1100") as error:
				split._validate_result(self.so, self.so, "SOURCE", self.source, {}, {"parent": {"grand_total": 1000}, "stock_qty": Decimal("10")})
		self.assertIn("Stock quantity: 10 → 15", str(error.exception))
