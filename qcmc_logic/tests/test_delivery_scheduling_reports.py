from unittest import TestCase
from unittest.mock import MagicMock, patch

import frappe

from qcmc_logic.qcmc_logics.report.delivery_note_stock_confirmation import (
	delivery_note_stock_confirmation as logistics,
)
from qcmc_logic.qcmc_logics.report.sales_order_delivery_scheduling import (
	sales_order_delivery_scheduling as scheduling,
)
from qcmc_logic.qcmc_logics.report.delivery_note_printing import (
	delivery_note_printing as printing,
)


class TestSalesOrderDeliveryScheduling(TestCase):
	def test_rejects_user_without_sales_coordinator_role(self):
		with (
			patch.object(scheduling.frappe, "session", frappe._dict(user="other@example.com")),
			patch.object(scheduling.frappe, "get_roles", return_value=["Sales User"]),
		):
			with self.assertRaises(frappe.PermissionError):
				scheduling._validate_scheduling_role()

	def test_allows_sales_coordinator_without_system_manager(self):
		with (
			patch.object(scheduling.frappe, "session", frappe._dict(user="coordinator@example.com")),
			patch.object(scheduling.frappe, "get_roles", return_value=["Sales Coordinator"]),
		):
			scheduling._validate_scheduling_role()

	def test_locks_selected_items_before_allocation(self):
		rows = [frappe._dict(name="SOI-1", parent="SO-1"), frappe._dict(name="SOI-2", parent="SO-1")]
		with patch.object(scheduling.frappe.db, "sql", return_value=rows) as sql:
			result = scheduling._lock_sales_order_items(["SOI-2", "SOI-1"])
		query, values = sql.call_args.args
		self.assertIn("FOR UPDATE", query)
		self.assertEqual(values, ("SOI-1", "SOI-2"))
		self.assertEqual(result, rows)

	def test_consolidates_matching_so_item_balances(self):
		rows = [
			frappe._dict(
				sales_order="SO-1", item_code="ITEM-1", warehouse="WH-1",
				so_detail="SOI-1", delivery_date="2026-09-10", available_from="2026-09-10",
				qty=50, delivered_qty=0, balance_qty=50, draft_dr_qty=0, available_qty=50,
			),
			frappe._dict(
				sales_order="SO-1", item_code="ITEM-1", warehouse="WH-1",
				so_detail="SOI-2", delivery_date="2026-09-11", available_from="2026-09-11",
				qty=50, delivered_qty=0, balance_qty=50, draft_dr_qty=0, available_qty=50,
			),
		]
		result = scheduling._consolidate_rows(rows)
		self.assertEqual(len(result), 1)
		self.assertEqual(result[0].available_qty, 100)
		self.assertEqual(result[0].so_details, ["SOI-1", "SOI-2"])
		self.assertEqual(result[0].delivery_dates, "2026-09-10, 2026-09-11")

	def test_created_dn_uses_ignore_permissions_and_available_qty(self):
		item = frappe._dict(so_detail="SOI-1", qty=10, rate=2, base_rate=2)
		dn = MagicMock()
		dn.name = "DN-1"
		dn.items = [item]
		dn.get.return_value = dn.items
		with (
			patch.object(scheduling, "_validate_scheduling_role"),
			patch.object(scheduling, "_lock_sales_order_items", return_value=[frappe._dict(name="SOI-1", parent="SO-1")]),
			patch.object(scheduling.frappe, "get_doc", return_value=frappe._dict(name="SO-1")),
			patch.object(scheduling, "_validate_sales_order", return_value={"SOI-1": 4}),
			patch("erpnext.selling.doctype.sales_order.sales_order.make_delivery_note", return_value=dn),
			patch("erpnext.stock.doctype.packed_item.packed_item.make_packing_list"),
		):
			scheduling.create_delivery_notes(["SOI-1"])
		self.assertEqual(item.qty, 4)
		dn.insert.assert_called_once_with(ignore_permissions=True)
		dn.db_set.assert_called_once_with("workflow_state", "For Stock Confirmation")


class TestDeliveryNoteStockConfirmation(TestCase):
	def test_rejects_user_without_stock_confirm_role(self):
		with (
			patch.object(logistics.frappe, "session", frappe._dict(user="other@example.com")),
			patch.object(logistics.frappe, "get_roles", return_value=["Stock User"]),
		):
			with self.assertRaises(frappe.PermissionError):
				logistics._validate_logistics_role()

	def test_allows_stock_confirm_user_without_system_manager(self):
		with (
			patch.object(logistics.frappe, "session", frappe._dict(user="logistics@example.com")),
			patch.object(logistics.frappe, "get_roles", return_value=["Stock Confirm User"]),
		):
			logistics._validate_logistics_role()

	def test_quantity_adjustment_saves_dn_with_controlled_permission_bypass(self):
		item = frappe._dict(name="DNI-1", item_code="ITEM-1", qty=10, rate=2, base_rate=2)
		doc = MagicMock(items=[item])
		with (
			patch.object(logistics.frappe.db, "get_value", return_value="DN-1"),
			patch.object(logistics.frappe, "get_doc", return_value=doc),
			patch.object(logistics, "_validate_delivery_note"),
			patch.object(logistics, "_set_next_scheduling_date"),
		):
			logistics.adjust_item_quantity("DNI-1", 6, "2026-09-10", "Partial stock")
		self.assertEqual(item.qty, 6)
		doc.save.assert_called_once_with(ignore_permissions=True)

	def test_confirmation_does_not_require_delivery_note_write_permission(self):
		doc = MagicMock()
		with (
			patch.object(logistics.frappe, "get_doc", return_value=doc),
			patch.object(logistics, "_validate_delivery_note"),
		):
			logistics.confirm_delivery_notes(["DN-1"], "Available")
		self.assertEqual(doc.workflow_state, "For DR Printing")
		self.assertEqual(doc.status, "For DR Printing")
		doc.save.assert_called_once_with(ignore_permissions=True)


class TestDeliveryNotePrinting(TestCase):
	def test_rejects_user_without_invoicing_clerk_role(self):
		with (
			patch.object(printing.frappe, "session", frappe._dict(user="other@example.com")),
			patch.object(printing.frappe, "get_roles", return_value=["Stock User"]),
		):
			with self.assertRaises(frappe.PermissionError):
				printing._validate_invoicing_role()

	def test_assigns_unique_dr_number_with_controlled_permission_bypass(self):
		doc = MagicMock()
		doc.name = "DN-1"
		doc.company = "QC Styropackaging Corporation"
		with (
			patch.object(printing, "_validate_invoicing_role"),
			patch.object(printing, "_get_locked_delivery_note", return_value=doc),
			patch.object(printing, "_validate_delivery_note"),
			patch.object(printing.frappe.db, "get_value", return_value=None),
			patch.object(printing.frappe.cache, "lock", return_value=MagicMock(__enter__=MagicMock(), __exit__=MagicMock())),
		):
			result = printing.assign_dr_number("DN-1", "DR-100")
		self.assertEqual(doc.custom_dr_number, "DR-100")
		doc.save.assert_called_once_with(ignore_permissions=True)
		self.assertEqual(result["print_format"], "Deliver Receipt QC")

	def test_submit_requires_dr_number(self):
		doc = MagicMock()
		doc.name = "DN-1"
		doc.custom_dr_number = ""
		with (
			patch.object(printing, "_validate_invoicing_role"),
			patch.object(printing, "_get_locked_delivery_note", return_value=doc),
			patch.object(printing, "_validate_delivery_note"),
		):
			with self.assertRaises(frappe.ValidationError):
				printing.submit_for_delivery(["DN-1"])

	def test_submit_uses_controlled_workflow_transition(self):
		doc = MagicMock()
		doc.name = "DN-1"
		doc.custom_dr_number = "DR-100"
		with (
			patch.object(printing, "_validate_invoicing_role"),
			patch.object(printing, "_get_locked_delivery_note", return_value=doc),
			patch.object(printing, "_validate_delivery_note"),
		):
			printing.submit_for_delivery(["DN-1"])
		self.assertEqual(doc.workflow_state, "To Deliver and Bill")
		self.assertEqual(doc.status, "To Deliver and Bill")
		doc.save.assert_called_once_with(ignore_permissions=True)
