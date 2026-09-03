import queue
import threading
import uuid
import io
import unittest
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import nowdate

from qcmc_logic.api.stock_reconciliation import (
	_submit_adjustment_entries,
	_submit_increment_entries,
	PhysicalCountConflict,
	get_pcount_item_baseline,
	get_pcount_scan_details,
	get_pcount_state,
	submit_pcount_entries,
)
from qcmc_logic.overrides.stock_reconciliation import CustomStockReconciliation


class TestStockReconciliationIncrement(FrappeTestCase):
	def test_for_recon_does_not_infer_zero_counts(self):
		doc = CustomStockReconciliation({
			"doctype": "Stock Reconciliation",
			"custom_physical_count": 1,
			"workflow_state": "For Recon",
		})
		with (
			patch.object(doc, "capture_for_recon_count_corrections") as capture,
			patch.object(doc, "add_missing_location_zero_counts") as infer_zero,
			patch.object(doc, "rebuild_physical_count_summary"),
			patch(
				"erpnext.stock.doctype.stock_reconciliation.stock_reconciliation.StockReconciliation.validate"
			),
		):
			doc.validate()
		capture.assert_called_once_with()
		infer_zero.assert_not_called()

	def test_close_inventory_infers_zero_counts(self):
		doc = CustomStockReconciliation({
			"doctype": "Stock Reconciliation",
			"custom_physical_count": 1,
			"workflow_state": "Close Inventory",
		})
		with (
			patch.object(doc, "capture_for_recon_count_corrections") as capture,
			patch.object(doc, "add_missing_location_zero_counts") as infer_zero,
			patch.object(doc, "rebuild_physical_count_summary"),
			patch(
				"erpnext.stock.doctype.stock_reconciliation.stock_reconciliation.StockReconciliation.validate"
			),
		):
			doc.validate()
		capture.assert_not_called()
		infer_zero.assert_called_once_with()

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
		entry.update(
			{
				"warehouse": self.warehouse,
				"inventoryLocation": location or self.locations[0],
				"quantity": delta,
				"quantityDelta": delta,
				"expectedPreviousCount": previous,
				"physicalCount": previous + delta,
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
			transactions=[self._transaction("ADD", 80, 160)],
			physicalCount=160,
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
		self.assertEqual([row.physical_count for row in doc.custom_physical_count_results], [260, 100260])
		self.assertEqual([row.quantity_delta for row in doc.custom_physical_count_results], [260, 100000])
		self.assertEqual([row.expected_previous_count for row in doc.custom_physical_count_results], [0, 260])
		self.assertEqual(self._summary_quantity(reconciliation), 100260)
		self.assertEqual(result["docstatus"], 0)
		self.assertEqual(result["status"], "Draft")

	def test_for_recon_manual_edit_appends_correction_snapshot(self):
		reconciliation = self._new_reconciliation()
		self._adjust(
			reconciliation,
			[self._adjustment_entry(0, 20, transactions=[self._transaction("ADD", 20, 20)])],
		)
		doc = frappe.get_doc("Stock Reconciliation", reconciliation)
		doc.workflow_state = "For Recon"
		doc.custom_physical_count_results[-1].physical_count = 15
		doc.save()

		doc.reload()
		self.assertEqual(len(doc.custom_physical_count_results), 2)
		self.assertEqual(doc.custom_physical_count_results[0].physical_count, 20)
		self.assertEqual(doc.custom_physical_count_results[0].status, "Old Count")
		self.assertEqual(doc.custom_physical_count_results[1].physical_count, 15)
		self.assertEqual(doc.custom_physical_count_results[1].quantity_delta, -5)
		self.assertEqual(doc.custom_physical_count_results[1].device_id, "ERP Review")
		self.assertEqual(self._summary_quantity(reconciliation), 15)

	def test_for_recon_can_correct_an_older_audit_snapshot(self):
		reconciliation = self._new_reconciliation()
		self._adjust(reconciliation, [self._adjustment_entry(0, 20, physicalCount=20)])
		self._adjust(reconciliation, [self._adjustment_entry(0, 80, physicalCount=100)])

		doc = frappe.get_doc("Stock Reconciliation", reconciliation)
		doc.workflow_state = "For Recon"
		doc.custom_physical_count_results[0].physical_count = 25
		doc.save()

		doc.reload()
		self.assertEqual(len(doc.custom_physical_count_results), 3)
		self.assertEqual(doc.custom_physical_count_results[0].physical_count, 20)
		self.assertEqual(doc.custom_physical_count_results[0].status, "Old Count")
		self.assertEqual(doc.custom_physical_count_results[1].physical_count, 100)
		self.assertEqual(doc.custom_physical_count_results[1].status, "Old Count")
		self.assertEqual(doc.custom_physical_count_results[2].physical_count, 25)
		self.assertEqual(doc.custom_physical_count_results[2].device_id, "ERP Review")
		self.assertEqual(self._summary_quantity(reconciliation), 25)

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
