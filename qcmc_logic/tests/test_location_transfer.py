import unittest
from decimal import Decimal
from unittest.mock import Mock, patch

import frappe

from qcmc_logic.api.location_transfer import (
	_destination_capacity, _quantity, _source_balance, create_location_transfer,
)
from qcmc_logic.api.warehouse_workflow import WorkflowError


class TestLocationTransfer(unittest.TestCase):
	request_id = "550e8400-e29b-41d4-a716-446655440000"

	def location(self, name, warehouse="FG - Test", **values):
		return frappe._dict({
			"name": name, "custom_warehouse": warehouse, "is_group": 0, "disabled": 0,
			"custom_restricted_item": "", "custom_storage_capacity": 0,
			**values,
		})

	def item(self, **values):
		return frappe._dict({
			"name": "ITEM-1", "item_name": "Item 1", "stock_uom": "PCS",
			"has_batch_no": 0, "has_serial_no": 0, **values,
		})

	def test_quantity_is_decimal_safe_and_positive(self):
		self.assertEqual(_quantity("1,250.50"), Decimal("1250.50"))
		for value in (None, "", 0, -1, "abc"):
			with self.subTest(value=value), self.assertRaises(WorkflowError):
				_quantity(value)

	def test_source_balance_uses_exact_location_only(self):
		with patch(
			"qcmc_logic.api.location_transfer.frappe.db.sql",
			side_effect=[[], [frappe._dict(quantity=5, row_count=1)], [(0,)]],
		):
			self.assertEqual(_source_balance(self.item(), "FG - Test", self.location("RACK-1")), 5)

	def test_destination_restriction_and_capacity_are_enforced(self):
		with self.assertRaises(WorkflowError) as restricted:
			_destination_capacity(self.item(), "Company", "FG - Test", self.location("RACK-2", custom_restricted_item="OTHER"), Decimal("1"))
		self.assertEqual(restricted.exception.code, "LOCATION_ITEM_MISMATCH")

		with patch("qcmc_logic.api.location_transfer.frappe.db.get_value", return_value="PUT-1"), patch(
			"qcmc_logic.api.location_transfer.frappe.db.sql", return_value=[(0,)]
		), patch(
			"qcmc_logic.api.location_transfer.get_available_dimension_putaway_capacity", return_value=10
		), patch("qcmc_logic.api.location_transfer._committed_location_quantities", return_value={"RACK-2": 7}):
			with self.assertRaises(WorkflowError) as capacity:
				_destination_capacity(self.item(), "Company", "FG - Test", self.location("RACK-2"), Decimal("4"))
		self.assertEqual(capacity.exception.code, "DESTINATION_CAPACITY_EXCEEDED")

	def base_patches(self, source, target, **extra):
		patches = [
			patch("qcmc_logic.api.location_transfer._auth", return_value="Administrator"),
			patch("qcmc_logic.api.location_transfer.begin_request", return_value=frappe._dict(
				name=self.request_id, operation="location_transfer.create", request_hash="hash",
				request_json="{}", user="Administrator", replay=None,
			)),
			patch("qcmc_logic.api.location_transfer._location", side_effect=[source, target]),
		]
		return patches

	def call_with_patches(self, source, target):
		patches = self.base_patches(source, target)
		for active in patches:
			active.start()
		try:
			return create_location_transfer("ITEM-1", source.name, target.name, 5, request_id=self.request_id)
		finally:
			for active in reversed(patches):
				active.stop()

	def test_same_location_and_cross_warehouse_are_rejected(self):
		result = self.call_with_patches(self.location("RACK-1"), self.location("RACK-1"))
		self.assertEqual(result["error_code"], "SOURCE_TARGET_SAME")
		result = self.call_with_patches(self.location("RACK-1", "FG-A"), self.location("RACK-2", "FG-B"))
		self.assertEqual(result["error_code"], "WAREHOUSE_MISMATCH")

	def test_identical_request_replays_without_creating_stock_entry(self):
		replay = {"success": True, "location_transfer": "LT-1", "duplicate_request": False}
		with patch("qcmc_logic.api.location_transfer._auth", return_value="Administrator"), patch(
			"qcmc_logic.api.location_transfer.begin_request", return_value=frappe._dict(replay=replay)
		), patch("qcmc_logic.api.location_transfer.frappe.get_doc") as get_doc:
			result = create_location_transfer("ITEM-1", "R1", "R2", 5, request_id=self.request_id)
		self.assertTrue(result["duplicate_request"])
		self.assertEqual(result["location_transfer"], "LT-1")
		get_doc.assert_not_called()

	def test_changed_payload_request_id_is_rejected(self):
		with patch("qcmc_logic.api.location_transfer._auth", return_value="Administrator"), patch(
			"qcmc_logic.api.location_transfer.begin_request",
			side_effect=WorkflowError("DUPLICATE_TRANSACTION", "mismatch"),
		):
			result = create_location_transfer("ITEM-1", "R1", "R2", 5, request_id=self.request_id)
		self.assertEqual(result["error_code"], "REQUEST_ID_PAYLOAD_MISMATCH")

	def test_same_warehouse_transfer_builds_and_submits_dimension_move(self):
		source, target, item = self.location("RACK-1"), self.location("RACK-2"), self.item()
		created = {}

		class LocationTransfer:
			name = "LT-1"
			docstatus = 0
			def __init__(self, data):
				self.data = data
			def insert(self, **_kwargs):
				created["location_transfer"] = self.data
			def submit(self):
				self.docstatus = 1

		def get_doc(data):
			return LocationTransfer(data)

		patches = self.base_patches(source, target)
		for active in patches: active.start()
		try:
			with patch("qcmc_logic.api.location_transfer._item", return_value=item), patch(
				"qcmc_logic.api.location_transfer._validate_tracking"
			), patch("qcmc_logic.api.location_transfer._source_balance", side_effect=[Decimal("10"), Decimal("10")]), patch(
				"qcmc_logic.api.location_transfer._destination_capacity"
			), patch("qcmc_logic.api.location_transfer.frappe.db.get_value", return_value="Company"), patch(
				"qcmc_logic.api.location_transfer.frappe.db.sql"
			), patch("qcmc_logic.api.location_transfer.active_employee", return_value=frappe._dict(name="EMP-1")), patch(
				"qcmc_logic.api.location_transfer.frappe.get_doc", side_effect=get_doc
			), patch("qcmc_logic.api.location_transfer.now_datetime", return_value="2026-09-10 10:00:00"), patch(
				"qcmc_logic.api.location_transfer.frappe.log_error"
			), patch("qcmc_logic.api.location_transfer.finish_request", side_effect=lambda _request, result: result):
				result = create_location_transfer("ITEM-1", source.name, target.name, 5, request_id=self.request_id)
		finally:
			for active in reversed(patches): active.stop()

		self.assertTrue(result["success"])
		self.assertEqual(result["docstatus"], 1)
		transfer = created["location_transfer"]
		self.assertEqual(transfer["warehouse"], "FG - Test")
		self.assertEqual((transfer["source_location"], transfer["target_location"]), ("RACK-1", "RACK-2"))
		self.assertEqual(transfer["request_id"], self.request_id)
