import queue
import threading
import uuid
import io
import json
import unittest
from unittest.mock import Mock, patch

import frappe
import qcmc_logic.api.stock_reconciliation as stock_reconciliation_api
from frappe.tests.utils import FrappeTestCase
from frappe.utils import nowdate

from qcmc_logic.api.stock_reconciliation import (
	_authenticate_request_user,
	_submit_adjustment_entries,
	_submit_increment_entries,
	_ensure_pcount_open_for_scanning,
	_get_physical_location_balances,
	_current_inventory_quantity,
	_get_unallocated_warehouse_balances,
	_resolve_increment_uom,
	PhysicalCountConflict,
	PhysicalCountNotOpen,
	post_pending_pcount_adjustments,
	get_pcount_item_baseline,
	get_pcount_reconciliation_review,
	get_pcount_scan_details,
	get_pcount_state,
	submit_pcount_entries,
)
from qcmc_logic.overrides.stock_reconciliation import (
	CustomStockReconciliation, effective_physical_count,
)


def run_cost_acct_cnt_tests():
	"""Run this feature's tests without triggering app-wide test discovery."""
	names = (
		"test_blank_cost_accounting_count_uses_physical_count",
		"test_entered_cost_accounting_count_overrides_physical_count",
		"test_for_recon_cost_accounting_count_overrides_physical_count",
		"test_for_recon_cost_accounting_count_can_exceed_physical_count",
		"test_for_recon_rejects_negative_cost_accounting_count",
		"test_cost_accounting_count_cannot_change_outside_for_recon",
		"test_physical_count_remains_immutable_during_for_recon",
		"test_for_recon_manual_count_creates_audited_missing_row",
		"test_manual_count_is_rejected_outside_for_recon",
		"test_manual_count_cannot_replace_an_existing_scanner_count",
		"test_for_recon_grid_row_is_hydrated_as_erp_manual_count",
	)
	suite = unittest.TestSuite(TestStockReconciliationIncrement(name) for name in names)
	result = unittest.TextTestRunner(verbosity=2).run(suite)
	if not result.wasSuccessful():
		raise AssertionError(
			f"Cost Acct Cnt tests failed: {len(result.failures)} failures, {len(result.errors)} errors"
		)
	return {"tests_run": result.testsRun, "successful": True}


def run_inventory_tag_tests():
	"""Run Inventory Tag coverage without unrelated reconciliation tests."""
	names = (
		"test_scan_transaction_has_searchable_inventory_tag_field",
		"test_adjustment_inventory_tags_remain_per_transaction_and_searchable",
		"test_adjustment_without_inventory_tag_remains_compatible",
		"test_increment_inventory_tag_is_saved_on_its_audit_transaction",
	)
	suite = unittest.TestSuite(TestStockReconciliationIncrement(name) for name in names)
	result = unittest.TextTestRunner(verbosity=2).run(suite)
	if not result.wasSuccessful():
		raise AssertionError(
			f"Inventory Tag tests failed: {len(result.failures)} failures, "
			f"{len(result.errors)} errors"
		)
	return {"tests_run": result.testsRun, "successful": True}


def run_inventory_tag_grouping_tests():
	"""Run Inventory Tag grouping coverage without unrelated reconciliation tests."""
	names = (
		"test_physical_count_result_has_inventory_tag_group_field",
		"test_inventory_tag_normalization_trims_only_surrounding_whitespace",
		"test_group_key_separates_tags_but_location_key_does_not",
		"test_latest_group_selection_keeps_each_inventory_tag",
		"test_same_inventory_tag_scans_update_one_active_detail_group",
		"test_different_inventory_tags_create_separate_detail_groups",
		"test_mixed_tagged_and_blank_transactions_share_location_total_only",
		"test_scan_transactions_remain_individual_under_group",
		"test_group_scan_history_accumulates_across_submissions",
		"test_replay_does_not_duplicate_group_quantity_or_transactions",
		"test_reused_transaction_id_with_changed_tag_is_rejected",
		"test_tag_group_cannot_be_deducted_below_zero",
		"test_same_tag_different_batch_or_serial_remains_separate",
		"test_concurrent_same_group_submissions_do_not_lose_delta",
		"test_cost_accounting_count_applies_independently_per_inventory_tag",
		"test_count_adjustment_variance_is_recount_minus_physical_count",
		"test_blank_cost_accounting_count_uses_group_physical_count",
		"test_physical_count_stays_immutable_per_tag_group",
		"test_summary_sums_effective_counts_across_tags",
		"test_summary_counts_location_erp_baseline_once_for_multiple_tags",
		"test_summary_still_combines_multiple_locations_by_item_warehouse",
		"test_posting_compares_combined_tag_count_to_location_stock_once",
		"test_posting_creates_one_net_adjustment_for_multiple_tags_at_location",
		"test_posting_links_adjustment_to_each_contributing_tag_group",
		"test_posting_keeps_count_adjustment_variance_on_tag_rows",
		"test_current_inventory_quantity_sums_latest_tag_groups",
		"test_physical_location_balances_sum_tags_before_later_movements",
		"test_putaway_capacity_uses_combined_effective_tag_count",
	)
	suite = unittest.TestSuite(TestStockReconciliationIncrement(name) for name in names)
	result = unittest.TextTestRunner(verbosity=2).run(suite)
	if not result.wasSuccessful():
		raise AssertionError(
			f"Inventory Tag grouping tests failed: {len(result.failures)} failures, "
			f"{len(result.errors)} errors"
		)
	return {"tests_run": result.testsRun, "successful": True}


def run_stock_reconciliation_increment_tests():
	"""Run this module without triggering unrelated app-wide test discovery."""
	suite = unittest.defaultTestLoader.loadTestsFromTestCase(TestStockReconciliationIncrement)
	result = unittest.TextTestRunner(verbosity=1).run(suite)
	if not result.wasSuccessful():
		raise AssertionError(
			f"Stock Reconciliation tests failed: {len(result.failures)} failures, "
			f"{len(result.errors)} errors"
		)
	return {"tests_run": result.testsRun, "successful": True}


class TestStockReconciliationIncrement(FrappeTestCase):
	def test_physical_count_result_has_inventory_tag_group_field(self):
		meta = frappe.get_meta("QCMC Physical Count Result")
		field = meta.get_field("inventory_tag")
		variance = meta.get_field("variance")

		self.assertIsNotNone(field)
		self.assertEqual(field.fieldtype, "Data")
		self.assertFalse(field.reqd)
		self.assertTrue(field.read_only)
		self.assertTrue(field.in_list_view)
		self.assertFalse(meta.has_field("custom_inventory_tag"))
		self.assertEqual(variance.label, "Count Adjustment Variance")

	def test_inventory_tag_normalization_trims_only_surrounding_whitespace(self):
		from qcmc_logic.physical_count_grouping import normalize_inventory_tag

		self.assertEqual(normalize_inventory_tag("  Inv  001  "), "Inv  001")
		self.assertEqual(normalize_inventory_tag(""), "")
		self.assertEqual(normalize_inventory_tag(None), "")

	def test_group_key_separates_tags_but_location_key_does_not(self):
		from qcmc_logic.physical_count_grouping import (
			physical_count_group_key,
			physical_count_location_key,
		)

		first = frappe._dict(
			item_code="ITEM-A", warehouse="FG - Test", location="LOC-1",
			batch_no="BATCH-1", serial_no="SERIAL-1", uom="PCS",
			inventory_tag="INV-001",
		)
		second = frappe._dict(first.copy())
		second.inventory_tag = "INV-002"

		self.assertNotEqual(physical_count_group_key(first), physical_count_group_key(second))
		self.assertEqual(physical_count_location_key(first), physical_count_location_key(second))

	def test_latest_group_selection_keeps_each_inventory_tag(self):
		from qcmc_logic.physical_count_grouping import latest_physical_count_groups

		rows = [
			frappe._dict(
				item_code="ITEM-A", warehouse="FG - Test", location="LOC-1", uom="PCS",
				inventory_tag="INV-001", submitted_at="2026-10-05 10:00:00", idx=1,
				physical_count=100,
			),
			frappe._dict(
				item_code="ITEM-A", warehouse="FG - Test", location="LOC-1", uom="PCS",
				inventory_tag="INV-001", submitted_at="2026-10-05 11:00:00", idx=2,
				physical_count=200,
			),
			frappe._dict(
				item_code="ITEM-A", warehouse="FG - Test", location="LOC-1", uom="PCS",
				inventory_tag="INV-002", submitted_at="2026-10-05 09:00:00", idx=3,
				physical_count=500,
			),
		]

		latest = latest_physical_count_groups(rows)

		self.assertEqual(len(latest), 2)
		self.assertEqual(sorted(row.physical_count for row in latest.values()), [200, 500])

	def test_scan_transaction_has_searchable_inventory_tag_field(self):
		field = frappe.get_meta("Physical Count Scan Transaction").get_field("inventory_tag")

		self.assertIsNotNone(field)
		self.assertEqual(field.fieldtype, "Data")
		self.assertFalse(frappe.get_meta("Physical Count Scan Transaction").has_field(
			"custom_inventory_tag"
		))

	def test_persistent_mobile_token_authenticates_scanner_request(self):
		from qcmc_logic.api.mobile_auth import issue_device_token

		issued = issue_device_token("Administrator", device_id="S2")
		original_user = frappe.session.user
		try:
			frappe.session.user = "Guest"
			self.assertEqual(
				_authenticate_request_user(issued.mobile_token),
				"Administrator",
			)
		finally:
			frappe.session.user = original_user

	def test_supplied_revoked_token_is_not_bypassed_by_authenticated_sid(self):
		from qcmc_logic.api.mobile_auth import issue_device_token, revoke_device_family

		issued = issue_device_token("Administrator", device_id="S2")
		revoke_device_family(issued.device_session, actor="Administrator")
		original_user = frappe.session.user
		try:
			frappe.session.user = "Administrator"
			self.assertIsNone(_authenticate_request_user(issued.mobile_token))
			self.assertEqual(frappe.session.user, "Administrator")
		finally:
			frappe.session.user = original_user

	def test_mobile_token_auth_sets_request_user_without_creating_login_session(self):
		original_user = frappe.session.user
		original_request = getattr(frappe.local, "request", None)
		try:
			frappe.session.user = "Guest"
			after_response = Mock()
			frappe.local.request = frappe._dict(
				after_response=frappe._dict(add=after_response)
			)
			with (
				patch.object(
					stock_reconciliation_api,
					"_resolve_mobile_token_user",
					return_value="scanner@example.com",
				),
				patch.object(stock_reconciliation_api.frappe, "set_user") as set_user,
				patch.object(stock_reconciliation_api.frappe.db, "commit") as commit,
			):
				user = _authenticate_request_user("valid-mobile-token")
				after_response.assert_called_once()
				after_response.call_args.args[0]()

			self.assertEqual(user, "scanner@example.com")
			self.assertEqual(set_user.call_args_list[0].args, ("scanner@example.com",))
			commit.assert_not_called()
			self.assertEqual(
				set_user.call_args_list[-1].args,
				("Guest",),
			)
		finally:
			frappe.session.user = original_user
			frappe.local.request = original_request

	def test_blank_cost_accounting_count_uses_physical_count(self):
		row = frappe._dict(physical_count=100, cost_acct_cnt=None)
		self.assertEqual(effective_physical_count(row), 100)

	def test_entered_cost_accounting_count_overrides_physical_count(self):
		zero = frappe._dict(physical_count=100, cost_acct_cnt=0)
		recount = frappe._dict(physical_count=100, cost_acct_cnt=80)
		self.assertEqual(effective_physical_count(zero), 0)
		self.assertEqual(effective_physical_count(recount), 80)

	def test_location_balance_uses_only_latest_submitted_count_snapshot(self):
		with patch("frappe.db.sql", return_value=[]) as sql:
			_get_physical_location_balances("FG - Test")

		query = sql.call_args.args[0]
		self.assertIn("row_number() over", query.lower())
		self.assertIn("where row_rank = 1", query.lower())
		self.assertNotIn("pcr.variance", query.lower())

	def test_unallocated_balance_is_bin_stock_less_physical_locations(self):
		physical = [frappe._dict(item_code="ITEM-A", quantity=10)]
		bin_rows = [frappe._dict(
			item_code="ITEM-A", item_name="Item A", stock_uom="PCS",
			warehouse="FG - Test", actual_qty=30,
		)]
		with patch("frappe.db.sql", return_value=bin_rows):
			rows = _get_unallocated_warehouse_balances("FG - Test", physical)

		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0].quantity, 20)

	def test_for_recon_and_close_inventory_are_not_open_for_scanning(self):
		for state in ("For Recon", "Close Inventory"):
			doc = frappe._dict(name="TEST-PCOUNT", docstatus=0, workflow_state=state)
			with self.assertRaises(PhysicalCountNotOpen):
				_ensure_pcount_open_for_scanning(doc)
		_ensure_pcount_open_for_scanning(
			frappe._dict(name="TEST-PCOUNT", docstatus=0, workflow_state="Draft")
		)

	def test_for_recon_does_not_infer_zero_counts(self):
		doc = CustomStockReconciliation({
			"doctype": "Stock Reconciliation",
			"custom_physical_count": 1,
			"workflow_state": "For Recon",
		})
		with (
			patch.object(doc, "validate_cost_accounting_adjustments") as validate_adjustments,
			patch.object(doc, "add_missing_location_zero_counts") as infer_zero,
			patch.object(doc, "rebuild_physical_count_summary"),
			patch(
				"erpnext.stock.doctype.stock_reconciliation.stock_reconciliation.StockReconciliation.validate"
			),
		):
			doc.validate()
		validate_adjustments.assert_called_once_with()
		infer_zero.assert_not_called()

	def test_close_inventory_does_not_infer_zero_counts(self):
		doc = CustomStockReconciliation({
			"doctype": "Stock Reconciliation",
			"custom_physical_count": 1,
			"workflow_state": "Close Inventory",
		})
		with (
			patch.object(doc, "validate_cost_accounting_adjustments") as validate_adjustments,
			patch.object(doc, "add_missing_location_zero_counts") as infer_zero,
			patch.object(doc, "rebuild_physical_count_summary"),
			patch(
				"erpnext.stock.doctype.stock_reconciliation.stock_reconciliation.StockReconciliation.validate"
			),
		):
			doc.validate()
		validate_adjustments.assert_called_once_with()
		infer_zero.assert_not_called()

	def test_summary_keeps_unscanned_location_stock_untouched(self):
		doc = CustomStockReconciliation({
			"doctype": "Stock Reconciliation",
			"custom_physical_count": 1,
			"custom_physical_count_results": [{
				"submission_id": "SCAN-1",
				"item_code": "ITEM-A",
				"warehouse": "FG - Test",
				"location": "COUNTED-LOCATION",
				"uom": "PCS",
				"physical_count": 40000,
				"cost_acct_cnt": 35000,
				"erp_quantity_before": 10000,
				"variance": 25000,
			}],
		})
		with patch("frappe.db.get_value", return_value=frappe._dict(
			actual_qty=25000, valuation_rate=0.30,
		)):
			doc.rebuild_physical_count_summary()

		self.assertEqual(doc.items[0].current_qty, 25000)
		self.assertEqual(doc.items[0].qty, 50000)

	def test_close_inventory_infers_zero_for_entirely_unscanned_item(self):
		doc = CustomStockReconciliation({
			"doctype": "Stock Reconciliation",
			"name": "TEST-COMPLETE-WAREHOUSE-COUNT",
			"set_warehouse": "FG - Test",
			"custom_physical_count": 1,
			"custom_physical_count_results": [{
				"submission_id": "SCAN-1",
				"item_code": "ITEM-SCANNED",
				"warehouse": "FG - Test",
				"inventory_location": "LOCATION-1",
				"location": "LOCATION-1",
				"uom": "PCS",
				"physical_count": 10,
			}],
		})
		balances = [frappe._dict(
			item_code="ITEM-NEVER-SCANNED",
			item_name="Never Scanned Item",
			stock_uom="PCS",
			warehouse="FG - Test",
			location="LOCATION-2",
			quantity=25,
		)]
		with patch(
			"qcmc_logic.api.stock_reconciliation._get_physical_location_balances",
			return_value=balances,
		), patch(
			"qcmc_logic.api.stock_reconciliation._get_unallocated_warehouse_balances",
			return_value=[],
		), patch("frappe.db.get_value", return_value="Location 2"):
			doc.add_missing_location_zero_counts()

		inferred = doc.custom_physical_count_results[-1]
		self.assertEqual(inferred.item_code, "ITEM-NEVER-SCANNED")
		self.assertEqual(inferred.location, "LOCATION-2")
		self.assertEqual(inferred.physical_count, 0)
		self.assertEqual(inferred.variance, -25)
		self.assertTrue(inferred.submission_id.startswith("AUTO-ZERO-"))

	def test_close_inventory_creates_unallocated_warehouse_zero(self):
		doc = CustomStockReconciliation({
			"doctype": "Stock Reconciliation",
			"name": "TEST-UNALLOCATED-WAREHOUSE-STOCK",
			"set_warehouse": "FG - Test",
			"custom_physical_count": 1,
			"custom_physical_count_results": [],
		})
		unallocated = [frappe._dict(
			item_code="ITEM-A", item_name="Item A", stock_uom="PCS",
			warehouse="FG - Test", quantity=20,
		)]
		with patch(
			"qcmc_logic.api.stock_reconciliation._get_physical_location_balances",
			return_value=[],
		), patch(
			"qcmc_logic.api.stock_reconciliation._get_unallocated_warehouse_balances",
			return_value=unallocated,
		):
			doc.add_missing_location_zero_counts()
			doc.add_missing_location_zero_counts()

		self.assertEqual(len(doc.custom_physical_count_results), 1)
		inferred = doc.custom_physical_count_results[0]
		self.assertTrue(inferred.submission_id.startswith("AUTO-UNALLOCATED-"))
		self.assertEqual(inferred.location, "")
		self.assertEqual(inferred.location_name, "Unallocated Warehouse Stock")
		self.assertEqual(inferred.erp_quantity_before, 20)
		self.assertEqual(inferred.physical_count, 0)
		self.assertEqual(inferred.variance, -20)

	def test_for_recon_review_lists_unscanned_book_stock(self):
		doc = frappe._dict(
			name="TEST-REVIEW",
			set_warehouse="FG - Test",
			custom_physical_count=1,
			custom_physical_count_results=[frappe._dict(
				submission_id="SCAN-1", item_code="ITEM-A", warehouse="FG - Test",
				location="LOCATION-1", inventory_location="LOCATION-1",
			)],
		)
		doc.check_permission = lambda permission: None
		balances = [
			frappe._dict(item_code="ITEM-A", item_name="Item A", stock_uom="PCS", warehouse="FG - Test", location="LOCATION-1", quantity=10),
			frappe._dict(item_code="ITEM-B", item_name="Item B", stock_uom="PCS", warehouse="FG - Test", location="LOCATION-2", quantity=25),
		]
		with patch("frappe.get_doc", return_value=doc), patch(
			"frappe.db.sql", return_value=balances
		), patch("frappe.get_all", return_value=[
			frappe._dict(name="LOCATION-1", location_code="L1", location_name="Location 1", location_type="Bin"),
			frappe._dict(name="LOCATION-2", location_code="L2", location_name="Location 2", location_type="Bin"),
			frappe._dict(name="LOCATION-3", location_code="L3", location_name="Location 3", location_type="Bin"),
		]), patch("frappe.db.get_value", return_value="Location 2"):
			review = get_pcount_reconciliation_review("TEST-REVIEW")

		self.assertEqual(review["unscanned_balance_count"], 2)
		self.assertEqual(review["never_scanned_item_count"], 1)
		self.assertEqual(review["location_without_count_count"], 2)
		rows = {row["storage_location"]: row for row in review["unscanned_balances"]}
		self.assertEqual(rows["LOCATION-2"]["item_code"], "ITEM-B")
		self.assertEqual(rows["LOCATION-3"]["book_quantity"], 0)
		self.assertEqual(rows["LOCATION-3"]["reason"], "No ERP stock")

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.company = frappe.db.get_single_value("Global Defaults", "default_company")
		if not cls.company:
			cls.company = frappe.get_all("Company", pluck="name", limit=1)[0]
		cls.abbr = frappe.db.get_value("Company", cls.company, "abbr")
		cls.uom = "Nos"
		if not frappe.db.exists("UOM", cls.uom):
			frappe.get_doc({"doctype": "UOM", "uom_name": cls.uom}).insert()

		cls.item_code = "_TEST-PC-INCREMENT-ITEM"
		if not frappe.db.exists("Item", cls.item_code):
			inventory_group = frappe.get_all("Inventory Group", pluck="name", limit=1)[0]
			frappe.get_doc(
				{
					"doctype": "Item",
					"item_code": cls.item_code,
					"item_name": cls.item_code,
					"item_group": "All Item Groups",
					"stock_uom": cls.uom,
					"is_stock_item": 1,
					"custom_inventory_group": inventory_group,
				}
			).insert()

		warehouse_name = "_Test Physical Count Increment"
		cls.warehouse = frappe.db.get_value(
			"Warehouse", {"warehouse_name": warehouse_name, "company": cls.company}, "name"
		)
		if not cls.warehouse:
			cls.warehouse = frappe.get_doc(
				{
					"doctype": "Warehouse",
					"warehouse_name": warehouse_name,
					"company": cls.company,
				}
			).insert().name

		cls.parent_location = "TEST-PC-INCREMENT-PARENT"
		if not frappe.db.exists("Storage Location", cls.parent_location):
			frappe.get_doc(
				{
					"doctype": "Storage Location",
					"location_code": cls.parent_location,
					"location_name": cls.parent_location,
					"location_type": "Aisle",
					"is_group": 1,
					"custom_warehouse": cls.warehouse,
				}
			).insert()

		cls.locations = []
		for suffix in ("A", "B"):
			location = f"TEST-PC-INCREMENT-{suffix}"
			if not frappe.db.exists("Storage Location", location):
				frappe.get_doc(
					{
						"doctype": "Storage Location",
						"location_code": location,
						"location_name": location,
						"location_type": "Bin",
						"is_group": 0,
						"parent_storage_location": cls.parent_location,
						"custom_warehouse": cls.warehouse,
					}
				).insert()
			cls.locations.append(location)
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		for name in frappe.get_all(
			"Physical Count Scan Transaction",
			filters={"reconciliation": ["like", "_TEST-PC-INC-%"]},
			pluck="name",
		):
			frappe.delete_doc("Physical Count Scan Transaction", name, force=True)
		for name in frappe.get_all(
			"Physical Count Submission",
			filters={"reconciliation": ["like", "_TEST-PC-INC-%"]},
			pluck="name",
		):
			frappe.delete_doc("Physical Count Submission", name, force=True)
		for name in frappe.get_all(
			"Stock Reconciliation", filters={"name": ["like", "_TEST-PC-INC-%"]}, pluck="name"
		):
			frappe.delete_doc("Stock Reconciliation", name, force=True)
		for location in reversed(cls.locations):
			if frappe.db.exists("Storage Location", location):
				frappe.delete_doc("Storage Location", location, force=True)
		if frappe.db.exists("Storage Location", cls.parent_location):
			frappe.delete_doc("Storage Location", cls.parent_location, force=True)
		if frappe.db.exists("Item", cls.item_code):
			frappe.delete_doc("Item", cls.item_code, force=True)
		if frappe.db.exists("Warehouse", cls.warehouse):
			frappe.delete_doc("Warehouse", cls.warehouse, force=True)
		frappe.db.commit()
		super().tearDownClass()

	def _new_reconciliation(self):
		name = f"_TEST-PC-INC-{uuid.uuid4().hex[:10]}"
		return frappe.get_doc(
			{
				"doctype": "Stock Reconciliation",
				"company": self.company,
				"purpose": "Stock Reconciliation",
				"posting_date": nowdate(),
				"set_warehouse": self.warehouse,
				"custom_physical_count": 1,
			}
		).insert(set_name=name).name

	def _entry(self, quantity, location=None, device="Scanner 1", lot_no="", uom=None, action=None):
		location = location or self.locations[0]
		entry = {
			"itemCode": self.item_code,
			"quantity": quantity,
			"uom": uom or self.uom,
			"lotNo": lot_no,
			"deviceId": device,
			"bin": {
				"warehouse": self.warehouse,
				"locationId": location,
				"locationCode": location,
				"locationName": location,
				"locationType": "Bin",
			},
		}
		if action:
			entry["action"] = action
		return entry

	def _increment(self, reconciliation, quantity, submission_id=None, **entry_kwargs):
		return _submit_increment_entries(
			reconciliation,
			submission_id or str(uuid.uuid4()),
			[self._entry(quantity, **entry_kwargs)],
			"Administrator",
		)

	def _quantity(self, reconciliation, location=None):
		return frappe.db.get_value(
			"Stock Reconciliation Item",
			{
				"parent": reconciliation,
				"item_code": self.item_code,
				"warehouse": self.warehouse,
				"location": location or self.locations[0],
			},
			"qty",
		)

	def _summary_quantity(self, reconciliation):
		return frappe.db.get_value(
			"Stock Reconciliation Item",
			{
				"parent": reconciliation,
				"item_code": self.item_code,
				"warehouse": self.warehouse,
			},
			"qty",
		)

	def _adjustment_entry(self, previous, delta, location=None, transactions=None, **values):
		entry = self._entry(abs(delta) or 0, location=location)
		final_count = values.get(
			"physicalCount", values.get("physical_count", previous + delta)
		)
		entry.update(
			{
				"warehouse": self.warehouse,
				"inventoryLocation": location or self.locations[0],
				"quantity": values.get("quantity", final_count),
				"quantityDelta": delta,
				"expectedPreviousCount": previous,
				"physicalCount": final_count,
				"totalAdded": max(previous + delta, 0),
				"totalDeducted": max(-delta, 0),
				"transactions": transactions or [],
			}
		)
		entry.update(values)
		return entry

	def _adjust(self, reconciliation, entries, submission_id=None):
		return _submit_adjustment_entries(
			reconciliation, submission_id or str(uuid.uuid4()), entries, "Administrator"
		)

	def _transaction(self, action, change, running, transaction_id=None):
		return {
			"id": transaction_id or str(uuid.uuid4()), "action": action,
			"quantityChange": change, "runningQuantity": running,
			"timestamp": "10:04:35 AM", "employeeId": "EMP-001",
			"employeeName": "Test Scanner", "deviceId": "Scanner 1",
		}

	def _tagged_transaction(self, tag, action, change, running, transaction_id=None):
		transaction = self._transaction(action, change, running, transaction_id)
		if tag is not None:
			transaction["inventoryTag"] = tag
		return transaction

	def _active_count_groups(self, reconciliation):
		doc = frappe.get_doc("Stock Reconciliation", reconciliation)
		return [row for row in doc.custom_physical_count_results if row.status != "Old Count"]

	def test_increment_first_then_adds_from_erp_total(self):
		reconciliation = self._new_reconciliation()
		first = self._increment(reconciliation, 5)
		second = self._increment(reconciliation, 3)
		self.assertEqual(first["updated_entries"][0]["total_quantity"], 5)
		self.assertEqual(first["updated_entries"][0]["item_name"], self.item_code)
		self.assertEqual(second["updated_entries"][0]["previous_quantity"], 5)
		self.assertEqual(self._quantity(reconciliation), 8)

	def test_replay_is_idempotent_and_changed_content_is_rejected(self):
		reconciliation = self._new_reconciliation()
		submission_id = str(uuid.uuid4())
		original = self._increment(reconciliation, 3, submission_id)
		replay = self._increment(reconciliation, 3, submission_id)
		self.assertFalse(original["duplicate_submission"])
		self.assertTrue(replay["duplicate_submission"])
		self.assertEqual(self._quantity(reconciliation), 3)
		self.assertEqual(
			frappe.db.count(
				"Physical Count Scan Transaction", {"reconciliation": reconciliation}
			),
			1,
		)
		with self.assertRaises(frappe.ValidationError):
			self._increment(reconciliation, 4, submission_id)
		self.assertEqual(self._quantity(reconciliation), 3)

	def test_deleted_row_restarts_from_zero(self):
		reconciliation = self._new_reconciliation()
		self._increment(reconciliation, 5)
		row = frappe.db.get_value("Stock Reconciliation Item", {"parent": reconciliation}, "name")
		frappe.delete_doc("Stock Reconciliation Item", row, force=True)
		frappe.db.commit()
		result = self._increment(reconciliation, 2)
		self.assertEqual(result["updated_entries"][0]["previous_quantity"], 0)
		self.assertEqual(self._quantity(reconciliation), 2)

	def test_different_bins_remain_separate(self):
		reconciliation = self._new_reconciliation()
		submission_id = str(uuid.uuid4())
		result = _submit_increment_entries(
			reconciliation,
			submission_id,
			[self._entry(4, self.locations[0]), self._entry(6, self.locations[1])],
			"Administrator",
		)
		self.assertEqual(result["item_count"], 2)
		self.assertEqual(self._quantity(reconciliation, self.locations[0]), 4)
		self.assertEqual(self._quantity(reconciliation, self.locations[1]), 6)

	def test_incrementing_second_rack_never_changes_first_rack(self):
		reconciliation = self._new_reconciliation()
		self._increment(reconciliation, 5, location=self.locations[0])
		self._increment(reconciliation, 3, location=self.locations[1])
		result = self._increment(reconciliation, 2, location=self.locations[0])
		self.assertEqual(result["updated_entries"][0]["storage_location"], self.locations[0])
		self.assertEqual(self._quantity(reconciliation, self.locations[0]), 7)
		self.assertEqual(self._quantity(reconciliation, self.locations[1]), 3)

	def test_physical_count_does_not_require_putaway_rule(self):
		reconciliation = self._new_reconciliation()
		result = self._increment(reconciliation, 3, location=self.locations[1])
		self.assertEqual(result["updated_entries"][0]["storage_location"], self.locations[1])
		self.assertEqual(self._quantity(reconciliation, self.locations[1]), 3)

	def test_missing_qr_warehouse_uses_reconciliation_default(self):
		reconciliation = self._new_reconciliation()
		entry = self._entry(2)
		entry["bin"].pop("warehouse")
		result = _submit_increment_entries(
			reconciliation, str(uuid.uuid4()), [entry], "Administrator"
		)
		self.assertEqual(result["updated_entries"][0]["warehouse"], self.warehouse)
		self.assertEqual(self._quantity(reconciliation), 2)

	def test_legacy_compact_warehouse_matches_reconciliation_default(self):
		reconciliation = self._new_reconciliation()
		entry = self._entry(2)
		entry["bin"]["warehouse"] = self.warehouse.replace(" - ", "-").replace(" ", "")
		result = _submit_increment_entries(
			reconciliation, str(uuid.uuid4()), [entry], "Administrator"
		)
		self.assertEqual(result["updated_entries"][0]["warehouse"], self.warehouse)
		self.assertEqual(self._quantity(reconciliation), 2)

	def test_deduct_updates_exact_location_and_creates_history(self):
		reconciliation = self._new_reconciliation()
		self._increment(reconciliation, 3, location=self.locations[0])
		self._increment(reconciliation, 4, location=self.locations[1])
		result = self._increment(
			reconciliation, 1, location=self.locations[1], action="DEDUCT"
		)
		updated = result["updated_entries"][0]
		self.assertEqual(updated["action"], "DEDUCT")
		self.assertEqual(updated["quantity_change"], -1)
		self.assertEqual(updated["total_quantity"], 3)
		self.assertEqual(self._quantity(reconciliation, self.locations[0]), 3)
		self.assertEqual(self._quantity(reconciliation, self.locations[1]), 3)
		history = frappe.get_all(
			"Physical Count Scan Transaction",
			filters={
				"reconciliation": reconciliation,
				"item_code": self.item_code,
				"storage_location": self.locations[1],
			},
			fields=["action", "quantity_change", "running_quantity"],
			order_by="creation asc",
		)
		self.assertEqual([row.action for row in history], ["ADD", "DEDUCT"])
		self.assertEqual([row.quantity_change for row in history], [4, -1])
		self.assertEqual([row.running_quantity for row in history], [4, 3])

	def test_deduct_below_zero_rolls_back_without_history(self):
		reconciliation = self._new_reconciliation()
		with self.assertRaises(frappe.ValidationError):
			self._increment(reconciliation, 1, action="DEDUCT")
		self.assertIsNone(self._quantity(reconciliation))
		self.assertFalse(
			frappe.db.exists(
				"Physical Count Scan Transaction", {"reconciliation": reconciliation}
			)
		)

	def test_lot_number_is_ignored_for_validation_and_matching(self):
		reconciliation = self._new_reconciliation()
		first = _submit_increment_entries(
			reconciliation,
			str(uuid.uuid4()),
			[self._entry(4, lot_no="NOT-AN-ERP-BATCH")],
			"Administrator",
		)
		second = _submit_increment_entries(
			reconciliation,
			str(uuid.uuid4()),
			[self._entry(6, lot_no="A-DIFFERENT-SCANNER-LOT")],
			"Administrator",
		)
		row = frappe.db.get_value(
			"Stock Reconciliation Item",
			{"parent": reconciliation},
			["qty", "batch_no"],
			as_dict=True,
		)
		self.assertEqual(first["updated_entries"][0]["total_quantity"], 4)
		self.assertEqual(second["updated_entries"][0]["previous_quantity"], 4)
		self.assertEqual(row.qty, 10)
		self.assertFalse(row.batch_no)

	def test_plural_scanner_uom_resolves_to_erp_stock_uom(self):
		reconciliation = self._new_reconciliation()
		result = _submit_increment_entries(
			reconciliation,
			str(uuid.uuid4()),
			[self._entry(5, uom=f"{self.uom}S")],
			"Administrator",
		)
		row = frappe.db.get_value(
			"Stock Reconciliation Item",
			{"parent": reconciliation},
			["qty", "stock_uom"],
			as_dict=True,
		)
		self.assertEqual(result["updated_entries"][0]["uom"], self.uom)
		self.assertEqual(row.stock_uom, self.uom)
		self.assertEqual(row.qty, 5)

	def test_blank_legacy_qr_uom_uses_erp_stock_uom(self):
		self.assertEqual(_resolve_increment_uom("", "PCS", 1), "PCS")
		self.assertEqual(_resolve_increment_uom(None, "PCS", 1), "PCS")
		with self.assertRaises(frappe.ValidationError):
			_resolve_increment_uom("", "", 1)

	def test_barcode_uom_does_not_override_authoritative_erp_stock_uom(self):
		self.assertEqual(_resolve_increment_uom("PCK", "PC", 1), "PC")

	def test_invalid_quantity_rolls_back_complete_request(self):
		reconciliation = self._new_reconciliation()
		with self.assertRaises(frappe.ValidationError):
			_submit_increment_entries(
				reconciliation,
				str(uuid.uuid4()),
				[self._entry(5), self._entry(float("nan"), self.locations[1])],
				"Administrator",
			)
		self.assertIsNone(self._quantity(reconciliation))

	def test_legacy_request_does_not_enter_increment_path(self):
		reconciliation = self._new_reconciliation()
		with patch(
			"qcmc_logic.api.stock_reconciliation._submit_increment_entries"
		) as increment_handler:
			result = submit_pcount_entries(reconciliation, [])
		increment_handler.assert_not_called()
		self.assertFalse(result["success"])
		self.assertNotIn("operation", result)

	def test_missing_item_error_precedes_reconciliation_validation_for_all_submit_modes(self):
		missing_item = "_TEST-PC-MISSING-ITEM"
		entry = self._entry(5)
		entry["itemCode"] = missing_item
		for operation in ("ADJUSTMENT", "INCREMENT", None):
			with self.subTest(operation=operation), patch(
				"qcmc_logic.api.stock_reconciliation._authenticate_request_user",
				return_value="Administrator",
			):
				response = submit_pcount_entries(
					"_MISSING-RECONCILIATION",
					[entry],
					operation=operation,
					submission_id=str(uuid.uuid4()),
				)

			self.assertFalse(response["success"])
			self.assertEqual(response["error_code"], "ITEM_NOT_FOUND")
			self.assertEqual(response["item_code"], missing_item)
			self.assertEqual(response["row_number"], 1)
			self.assertIn(missing_item, response["message"])

	def test_two_concurrent_devices_do_not_lose_updates(self):
		reconciliation = self._new_reconciliation()
		frappe.db.commit()
		site = frappe.local.site
		results = queue.Queue()
		barrier = threading.Barrier(2)

		def submit(quantity, device):
			try:
				frappe.init(site=site)
				frappe.connect()
				frappe.set_user("Administrator")
				barrier.wait()
				results.put(
					_submit_increment_entries(
						reconciliation,
						str(uuid.uuid4()),
						[self._entry(quantity, device=device)],
						"Administrator",
					)
				)
			except Exception as exc:
				results.put(exc)
			finally:
				frappe.destroy()

		threads = [
			threading.Thread(target=submit, args=(4, "Scanner A")),
			threading.Thread(target=submit, args=(6, "Scanner B")),
		]
		for thread in threads:
			thread.start()
		for thread in threads:
			thread.join(timeout=20)
		outcomes = [results.get_nowait(), results.get_nowait()]
		for outcome in outcomes:
			if isinstance(outcome, Exception):
				raise outcome
		frappe.db.commit()
		self.assertEqual(self._quantity(reconciliation), 10)

	def test_adjustment_positive_and_negative_with_audit(self):
		reconciliation = self._new_reconciliation()
		added = self._adjustment_entry(0, 5, transactions=[self._transaction("ADD", 5, 5)])
		self._adjust(reconciliation, [added])
		deducted = self._adjustment_entry(
			0, -2, transactions=[self._transaction("DEDUCT", -2, 3)], physicalCount=3
		)
		result = self._adjust(reconciliation, [deducted])
		self.assertEqual(result["results"][0]["physical_count"], 3)
		self.assertEqual(self._summary_quantity(reconciliation), 3)
		actions = frappe.get_all(
			"Physical Count Scan Transaction", {"reconciliation": reconciliation},
			pluck="action", order_by="creation asc",
		)
		self.assertEqual(actions, ["ADD", "SUBMITTED", "DEDUCT", "SUBMITTED"])

	def test_adjustment_uses_signed_delta_with_positive_final_quantity(self):
		reconciliation = self._new_reconciliation()
		self._adjust(reconciliation, [self._adjustment_entry(0, 1500)])
		correction = self._adjustment_entry(
			1500,
			-500,
			transactions=[self._transaction("DEDUCT", -500, 1000)],
			expectedPreviousCount=0,
		)
		result = self._adjust(reconciliation, [correction])

		self.assertEqual(correction["quantity"], 1000)
		self.assertEqual(correction["quantityDelta"], -500)
		self.assertEqual(correction["physicalCount"], 1000)
		self.assertEqual(result["results"][0]["physical_count"], 1000)

	def test_adjustment_quantity_is_final_count_fallback(self):
		reconciliation = self._new_reconciliation()
		entry = self._adjustment_entry(0, 5)
		entry.pop("physicalCount")

		result = self._adjust(reconciliation, [entry])

		self.assertEqual(result["results"][0]["physical_count"], 5)

	def test_adjustment_rejects_inconsistent_final_count(self):
		reconciliation = self._new_reconciliation()
		entry = self._adjustment_entry(0, 5, physicalCount=7, quantity=7)

		with self.assertRaisesRegex(
			frappe.ValidationError,
			"final physical count 7.*previous count 0.*quantityDelta 5",
		):
			self._adjust(reconciliation, [entry])

	def test_adjustment_api_validation_error_includes_row_values(self):
		reconciliation = self._new_reconciliation()
		entry = self._adjustment_entry(0, -500)
		with patch(
			"qcmc_logic.api.stock_reconciliation._authenticate_request_user",
			return_value="Administrator",
		):
			response = submit_pcount_entries(
				reconciliation,
				[entry],
				operation="ADJUSTMENT",
				submission_id=str(uuid.uuid4()),
			)

		self.assertEqual(response["error_code"], "PCOUNT_VALIDATION_ERROR")
		self.assertEqual(response["item_code"], self.item_code)
		self.assertEqual(response["inventory_location"], self.locations[0])
		self.assertEqual(response["quantity"], -500)
		self.assertEqual(response["quantity_delta"], -500)
		self.assertEqual(response["physical_count"], -500)
		for value in (
			self.item_code,
			self.locations[0],
			"quantity=-500",
			"quantity_delta=-500",
			"physical_count=-500",
		):
			self.assertIn(str(value), response["message"])

	def test_adjustment_error_context_recognizes_erpnext_row_format(self):
		entry = self._adjustment_entry(1500, -500)
		context = stock_reconciliation_api._adjustment_validation_context(
			[entry], frappe.ValidationError("[Row #1] Negative Quantity is not allowed")
		)

		self.assertEqual(context["item_code"], self.item_code)
		self.assertEqual(context["inventory_location"], self.locations[0])
		self.assertEqual(context["quantity_delta"], -500)

	def test_adjustment_exact_location_and_conflict(self):
		reconciliation = self._new_reconciliation()
		self._adjust(reconciliation, [self._adjustment_entry(0, 5, self.locations[0])])
		self._adjust(reconciliation, [self._adjustment_entry(0, 3, self.locations[1])])
		self._adjust(
			reconciliation,
			[self._adjustment_entry(0, -1, self.locations[1], physicalCount=2)],
		)
		self.assertEqual(self._summary_quantity(reconciliation), 7)
		with patch(
			"qcmc_logic.api.stock_reconciliation._current_inventory_quantity",
			return_value=5,
		):
			with self.assertRaises(PhysicalCountConflict) as conflict:
				self._adjust(reconciliation, [self._adjustment_entry(0, 1, self.locations[0])])
		self.assertEqual(conflict.exception.current_quantity, 5)

	def test_adjustment_does_not_add_erp_baseline_to_first_physical_count(self):
		reconciliation = self._new_reconciliation()
		entry = self._adjustment_entry(
			80,
			80,
			transactions=[self._transaction("ADD", 80, 80)],
			physicalCount=80,
			expectedPreviousCount=0,
			expectedERPQuantity=80,
		)
		with patch(
			"qcmc_logic.api.stock_reconciliation._current_inventory_quantity",
			return_value=80,
		):
			result = self._adjust(reconciliation, [entry])

		self.assertEqual(result["results"][0]["physical_count"], 80)
		doc = frappe.get_doc("Stock Reconciliation", reconciliation)
		count = doc.custom_physical_count_results[-1]
		self.assertEqual(count.expected_previous_count, 0)
		self.assertEqual(count.physical_count, 80)
		self.assertEqual(count.variance, 0)
		history = frappe.get_all(
			"Physical Count Scan Transaction",
			filters={"reconciliation": reconciliation, "action": "ADD"},
			fields=["previous_quantity", "running_quantity"],
		)
		self.assertEqual(history[0].previous_quantity, 0)
		self.assertEqual(history[0].running_quantity, 80)

	def test_adjustment_never_builds_target_below_counted_quantity_when_location_baseline_is_stale(self):
		reconciliation = self._new_reconciliation()
		entry = self._adjustment_entry(
			0,
			100,
			physicalCount=100,
			expectedERPQuantity=500,
		)
		with patch(
			"qcmc_logic.api.stock_reconciliation._current_inventory_quantity",
			return_value=500,
		):
			result = self._adjust(reconciliation, [entry])

		self.assertTrue(result["success"])
		self.assertEqual(self._summary_quantity(reconciliation), 100)

	def test_followup_snapshot_replaces_prior_snapshot_without_losing_audit(self):
		reconciliation = self._new_reconciliation()
		first = self._adjustment_entry(
			0, 260, transactions=[self._transaction("ADD", 260, 260)]
		)
		followup = self._adjustment_entry(
			0,
			100000,
			transactions=[self._transaction("ADD", 100000, 100260)],
			physicalCount=100260,
		)
		self._adjust(reconciliation, [first])
		result = self._adjust(reconciliation, [followup])

		doc = frappe.get_doc("Stock Reconciliation", reconciliation)
		self.assertEqual([row.physical_count for row in doc.custom_physical_count_results], [100260])
		self.assertEqual([row.quantity_delta for row in doc.custom_physical_count_results], [100000])
		self.assertEqual([row.expected_previous_count for row in doc.custom_physical_count_results], [260])
		self.assertEqual(self._summary_quantity(reconciliation), 100260)
		self.assertEqual(result["docstatus"], 0)
		self.assertEqual(result["status"], "Draft")

	def test_for_recon_cost_accounting_count_overrides_physical_count(self):
		reconciliation = self._new_reconciliation()
		self._adjust(
			reconciliation,
			[self._adjustment_entry(0, 20, transactions=[self._transaction("ADD", 20, 20)])],
		)
		doc = frappe.get_doc("Stock Reconciliation", reconciliation)
		doc.workflow_state = "For Recon"
		doc.custom_physical_count_results[-1].cost_acct_cnt = 15
		doc.save()

		doc.reload()
		self.assertEqual(len(doc.custom_physical_count_results), 1)
		self.assertEqual(doc.custom_physical_count_results[0].physical_count, 20)
		self.assertEqual(float(doc.custom_physical_count_results[0].cost_acct_cnt), 15)
		self.assertEqual(doc.custom_physical_count_results[0].variance, -5)
		self.assertEqual(self._summary_quantity(reconciliation), 15)

	def test_for_recon_cost_accounting_count_can_exceed_physical_count(self):
		reconciliation = self._new_reconciliation()
		self._adjust(reconciliation, [self._adjustment_entry(0, 100, physicalCount=100)])

		doc = frappe.get_doc("Stock Reconciliation", reconciliation)
		doc.workflow_state = "For Recon"
		doc.custom_physical_count_results[0].cost_acct_cnt = 120
		doc.save()

		doc.reload()
		self.assertEqual(doc.custom_physical_count_results[0].physical_count, 100)
		self.assertEqual(float(doc.custom_physical_count_results[0].cost_acct_cnt), 120)
		self.assertEqual(doc.custom_physical_count_results[0].variance, 20)
		self.assertEqual(self._summary_quantity(reconciliation), 120)

	def test_for_recon_rejects_negative_cost_accounting_count(self):
		reconciliation = self._new_reconciliation()
		self._adjust(reconciliation, [self._adjustment_entry(0, 20, physicalCount=20)])

		doc = frappe.get_doc("Stock Reconciliation", reconciliation)
		doc.workflow_state = "For Recon"
		doc.custom_physical_count_results[0].cost_acct_cnt = -1
		with self.assertRaisesRegex(frappe.ValidationError, "cannot be negative"):
			doc.save()

	def test_cost_accounting_count_cannot_change_outside_for_recon(self):
		reconciliation = self._new_reconciliation()
		self._adjust(reconciliation, [self._adjustment_entry(0, 20, physicalCount=20)])

		doc = frappe.get_doc("Stock Reconciliation", reconciliation)
		doc.custom_physical_count_results[0].cost_acct_cnt = 5
		with self.assertRaisesRegex(frappe.ValidationError, "only be changed during For Recon"):
			doc.save()

	def test_physical_count_remains_immutable_during_for_recon(self):
		reconciliation = self._new_reconciliation()
		self._adjust(reconciliation, [self._adjustment_entry(0, 20, physicalCount=20)])

		doc = frappe.get_doc("Stock Reconciliation", reconciliation)
		doc.workflow_state = "For Recon"
		doc.custom_physical_count_results[0].physical_count = 25
		with self.assertRaisesRegex(frappe.ValidationError, "cannot be edited"):
			doc.save()

	def test_for_recon_manual_count_creates_audited_missing_row(self):
		self.assertTrue(
			hasattr(stock_reconciliation_api, "add_manual_pcount_row"),
			"For Recon manual-count endpoint is missing",
		)
		reconciliation = self._new_reconciliation()
		doc = frappe.get_doc("Stock Reconciliation", reconciliation)
		doc.workflow_state = "For Recon"
		doc.save()

		result = stock_reconciliation_api.add_manual_pcount_row(
			reconciliation, self.item_code, self.locations[0], 12
		)

		doc.reload()
		row = doc.custom_physical_count_results[0]
		self.assertEqual(row.physical_count, 12)
		self.assertEqual(row.device_id, "ERP Manual")
		self.assertEqual(row.scanner_user, "Administrator")
		self.assertTrue(row.submission_id.startswith("ERP-MANUAL-"))
		self.assertEqual(self._summary_quantity(reconciliation), 12)
		self.assertEqual(result["physical_count"], 12)

	def test_manual_count_is_rejected_outside_for_recon(self):
		reconciliation = self._new_reconciliation()
		with self.assertRaisesRegex(frappe.ValidationError, "only allowed during For Recon"):
			stock_reconciliation_api.add_manual_pcount_row(
				reconciliation, self.item_code, self.locations[0], 12
			)

	def test_manual_count_cannot_replace_an_existing_scanner_count(self):
		reconciliation = self._new_reconciliation()
		self._adjust(reconciliation, [self._adjustment_entry(0, 20, physicalCount=20)])
		doc = frappe.get_doc("Stock Reconciliation", reconciliation)
		doc.workflow_state = "For Recon"
		doc.save()

		with self.assertRaisesRegex(frappe.ValidationError, "Use Cost Acct Cnt"):
			stock_reconciliation_api.add_manual_pcount_row(
				reconciliation, self.item_code, self.locations[0], 12
			)

	def test_for_recon_grid_row_is_hydrated_as_erp_manual_count(self):
		reconciliation = self._new_reconciliation()
		doc = frappe.get_doc("Stock Reconciliation", reconciliation)
		doc.workflow_state = "For Recon"
		doc.append("custom_physical_count_results", {
			"item_code": self.item_code,
			"warehouse": self.warehouse,
			"location": self.locations[0],
			"physical_count": 14,
		})
		doc.save()

		doc.reload()
		row = doc.custom_physical_count_results[0]
		self.assertTrue(row.submission_id.startswith("ERP-MANUAL-"))
		self.assertEqual(row.device_id, "ERP Manual")
		self.assertEqual(row.uom, self.uom)
		self.assertEqual(self._summary_quantity(reconciliation), 14)

	def test_adjustment_negative_missing_row_and_duplicate_submission(self):
		reconciliation = self._new_reconciliation()
		with self.assertRaises(frappe.ValidationError):
			self._adjust(reconciliation, [self._adjustment_entry(0, -1)])
		submission_id = str(uuid.uuid4())
		entry = self._adjustment_entry(0, 4)
		first = self._adjust(reconciliation, [entry], submission_id)
		replay = self._adjust(reconciliation, [entry], submission_id)
		self.assertFalse(first["duplicate_submission"])
		self.assertTrue(replay["duplicate_submission"])
		self.assertEqual(self._summary_quantity(reconciliation), 4)

	def test_adjustment_transaction_id_cannot_be_reused_across_submissions(self):
		reconciliation = self._new_reconciliation()
		transaction_id = str(uuid.uuid4())
		transaction = self._transaction("ADD", 4, 4, transaction_id)
		self._adjust(
			reconciliation,
			[self._adjustment_entry(0, 4, transactions=[transaction])],
		)
		with self.assertRaises(frappe.ValidationError):
			self._adjust(
				reconciliation,
				[self._adjustment_entry(0, 4, transactions=[transaction], physicalCount=4)],
			)
		self.assertEqual(self._summary_quantity(reconciliation), 4)
		self.assertEqual(
			frappe.db.count(
				"Physical Count Scan Transaction", {"transaction_id": transaction_id}
			),
			1,
		)

	def test_adjustment_inventory_tags_remain_per_transaction_and_searchable(self):
		reconciliation = self._new_reconciliation()
		submission_id = str(uuid.uuid4())
		first = self._transaction("ADD", 1000, 1000)
		first["inventoryTag"] = "  INV-001  "
		second = self._transaction("ADD", 1000, 2000)
		second["inventory_tag"] = "INV-002"
		entry = self._adjustment_entry(
			0, 2000, transactions=[first, second], physicalCount=2000
		)

		original = self._adjust(reconciliation, [entry], submission_id)
		replay = self._adjust(reconciliation, [entry], submission_id)

		self.assertFalse(original["duplicate_submission"])
		self.assertTrue(replay["duplicate_submission"])
		rows = frappe.get_all(
			"Physical Count Scan Transaction",
			filters={"transaction_id": ["in", [first["id"], second["id"]]]},
			fields=["transaction_id", "inventory_tag", "quantity_change"],
		)
		by_id = {row.transaction_id: row for row in rows}
		self.assertEqual(by_id[first["id"]].inventory_tag, "INV-001")
		self.assertEqual(by_id[second["id"]].inventory_tag, "INV-002")
		self.assertEqual(by_id[first["id"]].quantity_change, 1000)
		self.assertEqual(by_id[second["id"]].quantity_change, 1000)
		self.assertEqual(len(rows), 2)
		self.assertEqual(
			frappe.db.count(
				"Physical Count Scan Transaction",
				{"inventory_tag": "INV-002", "action": "ADD"},
			),
			1,
		)
		doc = frappe.get_doc("Stock Reconciliation", reconciliation)
		self.assertEqual(
			{
				row.inventory_tag: [
					transaction.get("inventoryTag")
					for transaction in json.loads(row.scan_history_json)
				]
				for row in doc.custom_physical_count_results
			},
			{"INV-001": ["INV-001"], "INV-002": ["INV-002"]},
		)
		self.assertEqual(
			sum(row.physical_count for row in doc.custom_physical_count_results), 2000
		)

	def test_same_inventory_tag_scans_update_one_active_detail_group(self):
		reconciliation = self._new_reconciliation()
		transactions = [
			self._tagged_transaction("INV-001", "ADD", 1000, 1000),
			self._tagged_transaction("INV-001", "ADD", 1000, 2000),
		]
		self._adjust(reconciliation, [self._adjustment_entry(0, 2000, transactions=transactions)])
		groups = self._active_count_groups(reconciliation)
		self.assertEqual([(row.inventory_tag, row.physical_count) for row in groups], [("INV-001", 2000)])

	def test_different_inventory_tags_create_separate_detail_groups(self):
		reconciliation = self._new_reconciliation()
		transactions = [
			self._tagged_transaction("INV-001", "ADD", 1000, 1000),
			self._tagged_transaction("INV-001", "ADD", 1000, 2000),
			self._tagged_transaction("INV-002", "ADD", 500, 2500),
		]
		self._adjust(reconciliation, [self._adjustment_entry(0, 2500, transactions=transactions)])
		groups = self._active_count_groups(reconciliation)
		self.assertEqual(
			{row.inventory_tag: row.physical_count for row in groups},
			{"INV-001": 2000, "INV-002": 500},
		)
		self.assertEqual(self._summary_quantity(reconciliation), 2500)

	def test_mixed_tagged_and_blank_transactions_share_location_total_only(self):
		reconciliation = self._new_reconciliation()
		transactions = [
			self._tagged_transaction(None, "ADD", 100, 100),
			self._tagged_transaction("INV-001", "ADD", 50, 150),
		]
		self._adjust(reconciliation, [self._adjustment_entry(0, 150, transactions=transactions)])
		groups = self._active_count_groups(reconciliation)
		self.assertEqual({row.inventory_tag or "": row.physical_count for row in groups}, {"": 100, "INV-001": 50})
		self.assertEqual(self._summary_quantity(reconciliation), 150)

	def test_scan_transactions_remain_individual_under_group(self):
		reconciliation = self._new_reconciliation()
		transactions = [
			self._tagged_transaction("INV-001", "ADD", 1000, 1000),
			self._tagged_transaction("INV-001", "ADD", 1000, 2000),
			self._tagged_transaction("INV-002", "ADD", 500, 2500),
		]
		self._adjust(reconciliation, [self._adjustment_entry(0, 2500, transactions=transactions)])
		self.assertEqual(
			frappe.db.count("Physical Count Scan Transaction", {"transaction_id": ["in", [tx["id"] for tx in transactions]]}),
			3,
		)

	def test_group_scan_history_accumulates_across_submissions(self):
		reconciliation = self._new_reconciliation()
		self._adjust(reconciliation, [self._adjustment_entry(0, 100, transactions=[self._tagged_transaction("INV-001", "ADD", 100, 100)])])
		self._adjust(reconciliation, [self._adjustment_entry(100, 50, transactions=[self._tagged_transaction("INV-001", "ADD", 50, 150)], expectedERPQuantity=0)])
		groups = self._active_count_groups(reconciliation)
		self.assertEqual(len(groups), 1)
		self.assertEqual(groups[0].physical_count, 150)
		self.assertEqual(groups[0].transaction_count, 2)
		self.assertEqual(len(json.loads(groups[0].scan_history_json)), 2)

	def test_replay_does_not_duplicate_group_quantity_or_transactions(self):
		reconciliation = self._new_reconciliation()
		submission_id = str(uuid.uuid4())
		transaction = self._tagged_transaction("INV-001", "ADD", 100, 100)
		entry = self._adjustment_entry(0, 100, transactions=[transaction])
		self._adjust(reconciliation, [entry], submission_id)
		replay = self._adjust(reconciliation, [entry], submission_id)
		self.assertTrue(replay["duplicate_submission"])
		self.assertEqual(self._active_count_groups(reconciliation)[0].physical_count, 100)
		self.assertEqual(frappe.db.count("Physical Count Scan Transaction", {"transaction_id": transaction["id"]}), 1)

	def test_reused_transaction_id_with_changed_tag_is_rejected(self):
		reconciliation = self._new_reconciliation()
		transaction_id = str(uuid.uuid4())
		first = self._tagged_transaction("INV-001", "ADD", 100, 100, transaction_id)
		self._adjust(reconciliation, [self._adjustment_entry(0, 100, transactions=[first])])
		changed = self._tagged_transaction("INV-002", "ADD", 100, 200, transaction_id)
		with self.assertRaisesRegex(frappe.ValidationError, "already been submitted"):
			self._adjust(reconciliation, [self._adjustment_entry(100, 100, transactions=[changed], expectedERPQuantity=0)])

	def test_tag_group_cannot_be_deducted_below_zero(self):
		reconciliation = self._new_reconciliation()
		transactions = [
			self._tagged_transaction("INV-001", "ADD", 5, 5),
			self._tagged_transaction("INV-002", "ADD", 10, 15),
		]
		self._adjust(reconciliation, [self._adjustment_entry(0, 15, transactions=transactions)])
		deduction = self._tagged_transaction("INV-001", "DEDUCT", -6, 9)
		with self.assertRaisesRegex(frappe.ValidationError, "cannot become negative"):
			self._adjust(reconciliation, [self._adjustment_entry(15, -6, transactions=[deduction], expectedERPQuantity=0)])

	def test_same_tag_different_batch_or_serial_remains_separate(self):
		from qcmc_logic.physical_count_grouping import physical_count_group_key
		first = frappe._dict(item_code=self.item_code, warehouse=self.warehouse, location=self.locations[0], uom=self.uom, batch_no="B1", inventory_tag="INV-001")
		second = frappe._dict(first.copy())
		second.batch_no = "B2"
		self.assertNotEqual(physical_count_group_key(first), physical_count_group_key(second))

	def test_concurrent_same_group_submissions_do_not_lose_delta(self):
		reconciliation = self._new_reconciliation()
		frappe.db.commit()
		site = frappe.local.site
		results = queue.Queue()
		barrier = threading.Barrier(2)

		def submit(delta):
			try:
				frappe.init(site=site)
				frappe.connect()
				frappe.set_user("Administrator")
				barrier.wait()
				transaction = self._tagged_transaction("INV-001", "ADD", delta, delta)
				results.put(_submit_adjustment_entries(reconciliation, str(uuid.uuid4()), [self._adjustment_entry(0, delta, transactions=[transaction])], "Administrator"))
			except Exception as exc:
				results.put(exc)
			finally:
				frappe.destroy()

		threads = [threading.Thread(target=submit, args=(40,)), threading.Thread(target=submit, args=(60,))]
		for thread in threads:
			thread.start()
		for thread in threads:
			thread.join(timeout=20)
		for _ in threads:
			outcome = results.get_nowait()
			if isinstance(outcome, Exception):
				raise outcome
		frappe.db.commit()
		self.assertEqual(self._active_count_groups(reconciliation)[0].physical_count, 100)

	def _reconciliation_with_reviewed_tag_groups(self):
		reconciliation = self._new_reconciliation()
		transactions = [
			self._tagged_transaction("INV-001", "ADD", 2000, 2000),
			self._tagged_transaction("INV-002", "ADD", 500, 2500),
		]
		self._adjust(reconciliation, [self._adjustment_entry(0, 2500, transactions=transactions)])
		doc = frappe.get_doc("Stock Reconciliation", reconciliation)
		doc.workflow_state = "For Recon"
		for row in doc.custom_physical_count_results:
			row.cost_acct_cnt = {"INV-001": 1900, "INV-002": 450}[row.inventory_tag]
		doc.save()
		doc.reload()
		return doc

	def test_cost_accounting_count_applies_independently_per_inventory_tag(self):
		doc = self._reconciliation_with_reviewed_tag_groups()
		self.assertEqual(
			{row.inventory_tag: float(row.cost_acct_cnt) for row in doc.custom_physical_count_results},
			{"INV-001": 1900, "INV-002": 450},
		)

	def test_count_adjustment_variance_is_recount_minus_physical_count(self):
		doc = self._reconciliation_with_reviewed_tag_groups()
		self.assertEqual(
			{row.inventory_tag: row.variance for row in doc.custom_physical_count_results},
			{"INV-001": -100, "INV-002": -50},
		)

	def test_blank_cost_accounting_count_uses_group_physical_count(self):
		from qcmc_logic.overrides.stock_reconciliation import effective_physical_count
		self.assertEqual(effective_physical_count(frappe._dict(physical_count=500, cost_acct_cnt=None)), 500)

	def test_physical_count_stays_immutable_per_tag_group(self):
		doc = self._reconciliation_with_reviewed_tag_groups()
		row = next(row for row in doc.custom_physical_count_results if row.inventory_tag == "INV-001")
		row.physical_count = 1800
		with self.assertRaisesRegex(frappe.ValidationError, "cannot be edited"):
			doc.save()

	def test_summary_sums_effective_counts_across_tags(self):
		doc = self._reconciliation_with_reviewed_tag_groups()
		self.assertEqual(self._summary_quantity(doc.name), 2350)

	def test_summary_counts_location_erp_baseline_once_for_multiple_tags(self):
		from qcmc_logic.physical_count_grouping import aggregate_physical_count_locations
		rows = [
			frappe._dict(item_code="ITEM-A", warehouse="FG", location="LOC", uom="PCS", inventory_tag="INV-001", physical_count=2000, cost_acct_cnt=1900, erp_quantity_before=2600),
			frappe._dict(item_code="ITEM-A", warehouse="FG", location="LOC", uom="PCS", inventory_tag="INV-002", physical_count=500, cost_acct_cnt=450, erp_quantity_before=2600),
		]
		aggregate = next(iter(aggregate_physical_count_locations(rows, lambda row: row.cost_acct_cnt).values()))
		self.assertEqual(aggregate.erp_quantity_before, 2600)
		self.assertEqual(aggregate.effective_count, 2350)

	def test_summary_still_combines_multiple_locations_by_item_warehouse(self):
		reconciliation = self._new_reconciliation()
		for location, tag, quantity in ((self.locations[0], "INV-001", 100), (self.locations[1], "INV-002", 50)):
			transaction = self._tagged_transaction(tag, "ADD", quantity, quantity)
			self._adjust(reconciliation, [self._adjustment_entry(0, quantity, location=location, transactions=[transaction])])
		self.assertEqual(self._summary_quantity(reconciliation), 150)

	def _run_reviewed_group_posting(self):
		doc = self._reconciliation_with_reviewed_tag_groups()
		created = frappe._dict(name="MAT-STE-TEST")
		with (
			patch("qcmc_logic.api.stock_reconciliation._current_inventory_quantity", return_value=0) as current,
			patch("qcmc_logic.api.stock_reconciliation._make_pcount_stock_entry", return_value=created) as make,
		):
			documents = post_pending_pcount_adjustments(doc)
		return doc, current, make, documents

	def test_posting_compares_combined_tag_count_to_location_stock_once(self):
		doc, current, _make, _documents = self._run_reviewed_group_posting()
		current.assert_called_once()

	def test_posting_creates_one_net_adjustment_for_multiple_tags_at_location(self):
		_doc, _current, make, documents = self._run_reviewed_group_posting()
		make.assert_called_once()
		self.assertEqual(make.call_args.args[2][0][1], 2350)
		self.assertEqual(documents, ["MAT-STE-TEST"])

	def test_posting_links_adjustment_to_each_contributing_tag_group(self):
		doc, _current, _make, _documents = self._run_reviewed_group_posting()
		self.assertEqual({row.adjustment_document for row in doc.custom_physical_count_results}, {"MAT-STE-TEST"})

	def test_posting_keeps_count_adjustment_variance_on_tag_rows(self):
		doc, _current, _make, _documents = self._run_reviewed_group_posting()
		self.assertEqual({row.inventory_tag: row.variance for row in doc.custom_physical_count_results}, {"INV-001": -100, "INV-002": -50})

	def test_current_inventory_quantity_sums_latest_tag_groups(self):
		with patch("frappe.db.sql", side_effect=[
			[frappe._dict(physical_count=2350, counted_at="2026-10-05")],
			[frappe._dict(quantity=0, row_count=0)],
			[(0,)],
		]) as sql:
			quantity = _current_inventory_quantity("ITEM-A", "FG", "LOC")
		self.assertEqual(quantity, 2350)
		query = sql.call_args_list[0].args[0].lower()
		self.assertIn("inventory_tag", query)
		self.assertIn("sum(", query)
		self.assertIn("and coalesce(pcr.batch_no", query)
		self.assertIn("and coalesce(pcr.serial_no", query)

	def test_physical_location_balances_sum_tags_before_later_movements(self):
		with patch("frappe.db.sql", return_value=[]) as sql:
			_get_physical_location_balances("FG")
		query = sql.call_args.args[0].lower()
		self.assertIn("inventory_tag", query)
		self.assertIn("sum(physical_count)", query)
		self.assertNotIn("pcr.variance", query)

	def test_putaway_capacity_uses_combined_effective_tag_count(self):
		from qcmc_logic.overrides.putaway_rule_dimension import get_location_total_physical_balance
		with patch("frappe.db.sql", return_value=[(0,)]) as sql:
			get_location_total_physical_balance("FG", "LOC")
		query = sql.call_args.args[0].lower()
		self.assertIn("inventory_tag", query)
		self.assertNotIn("select pcr.variance", query)

	def test_adjustment_without_inventory_tag_remains_compatible(self):
		reconciliation = self._new_reconciliation()
		transaction = self._transaction("ADD", 4, 4)

		self._adjust(
			reconciliation,
			[self._adjustment_entry(0, 4, transactions=[transaction])],
		)

		self.assertFalse(frappe.db.get_value(
			"Physical Count Scan Transaction", transaction["id"], "inventory_tag"
		))
		self.assertEqual(self._summary_quantity(reconciliation), 4)

	def test_increment_inventory_tag_is_saved_on_its_audit_transaction(self):
		reconciliation = self._new_reconciliation()
		submission_id = str(uuid.uuid4())
		entry = self._entry(3)
		entry["inventoryTag"] = "  INC-001  "

		_submit_increment_entries(
			reconciliation, submission_id, [entry], "Administrator"
		)

		self.assertEqual(
			frappe.db.get_value(
				"Physical Count Scan Transaction",
				f"{submission_id}:increment:1",
				"inventory_tag",
			),
			"INC-001",
		)
		self.assertEqual(self._quantity(reconciliation), 3)

	def test_adjustment_rejects_invalid_transaction_sign_and_running_count(self):
		reconciliation = self._new_reconciliation()
		invalid_add = self._adjustment_entry(
			0, -1, transactions=[self._transaction("ADD", -1, -1)], physicalCount=0
		)
		with self.assertRaises(frappe.ValidationError):
			self._adjust(reconciliation, [invalid_add])

		invalid_deduct = self._adjustment_entry(
			0, 1, transactions=[self._transaction("DEDUCT", 1, 1)], physicalCount=1
		)
		with self.assertRaises(frappe.ValidationError):
			self._adjust(reconciliation, [invalid_deduct])

		negative_running = self._adjustment_entry(
			0, -1, transactions=[self._transaction("DEDUCT", -1, -1)], physicalCount=0
		)
		with self.assertRaises(frappe.ValidationError):
			self._adjust(reconciliation, [negative_running])

	def test_adjustment_invalid_warehouse_location_and_atomic_rollback(self):
		reconciliation = self._new_reconciliation()
		invalid_warehouse = self._adjustment_entry(0, 1, warehouse="DOES-NOT-EXIST")
		with self.assertRaises(frappe.ValidationError):
			self._adjust(reconciliation, [invalid_warehouse])
		missing_location = self._adjustment_entry(0, 1)
		missing_location["inventoryLocation"] = ""
		missing_location["bin"].pop("locationId")
		with self.assertRaises(frappe.ValidationError):
			self._adjust(reconciliation, [missing_location])
		valid = self._adjustment_entry(0, 2, self.locations[0])
		invalid = self._adjustment_entry(0, -1, self.locations[1])
		with self.assertRaises(frappe.ValidationError):
			self._adjust(reconciliation, [valid, invalid])
		self.assertIsNone(self._quantity(reconciliation, self.locations[0]))

	def test_get_pcount_state_reads_only_current_rows(self):
		reconciliation = self._new_reconciliation()
		self.assertEqual(get_pcount_state(reconciliation)["entries"], [])
		self._adjust(reconciliation, [self._adjustment_entry(0, 2)])
		state = get_pcount_state(reconciliation)
		self.assertEqual(state["entries"], [])
		row = frappe.db.get_value("Stock Reconciliation Item", {"parent": reconciliation}, "name")
		frappe.delete_doc("Stock Reconciliation Item", row, force=True)
		frappe.db.commit()
		self.assertEqual(get_pcount_state(reconciliation)["entries"], [])
		self.assertTrue(frappe.db.exists("Physical Count Scan Transaction", {"reconciliation": reconciliation}))

	def test_offline_baseline_uses_exact_location_warehouse_and_batch(self):
		reconciliation = self._new_reconciliation()
		with patch(
			"qcmc_logic.api.stock_reconciliation._current_inventory_quantity",
			return_value=7,
		):
			baseline = get_pcount_item_baseline(
				reconciliation,
				self.item_code,
				self.warehouse,
				self.locations[0],
				batch_no="",
			)
		self.assertEqual(baseline["inventory_location"], self.locations[0])
		self.assertEqual(baseline["warehouse"], self.warehouse)
		self.assertEqual(baseline["current_erp_quantity"], 7)
		self.assertEqual(baseline["quantity"], 7)
		self.assertEqual(baseline["batch_no"], "")

		with self.assertRaises(frappe.ValidationError):
			get_pcount_item_baseline(
				reconciliation,
				self.item_code,
				"Wrong Warehouse",
				self.locations[0],
			)


def run_test_suite():
	stream = io.StringIO()
	suite = unittest.defaultTestLoader.loadTestsFromTestCase(TestStockReconciliationIncrement)
	result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
	if not result.wasSuccessful():
		raise AssertionError(stream.getvalue())
	return {"tests_run": result.testsRun, "output": stream.getvalue()}
