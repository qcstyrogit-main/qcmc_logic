import unittest
import json
from types import SimpleNamespace
from unittest.mock import patch

import frappe

from qcmc_logic.api.stock_entry_scanner import (
	ScannerAPIError,
	_item_result,
	_purpose,
	_resolve_finished_item_putaway,
	_putaway_allocations,
	_general_purpose_location,
	_parent_distribution,
	_resolve_storage_location,
	_validate_override_location,
	_normalize_warehouse,
	_validate_allocation_entry,
	_validate_distribution_parent,
	_validate_document,
	_split_finished_rows,
	_get_idempotent_replay,
	_job_card_id,
	_stock_entry_id,
	create_manufacture_receive_draft,
	get_manufacture_receive_context,
	update_manufacture_receive_draft,
	submit_manufacture_receive,
)
from qcmc_logic.www.storage_location_qr import _make_qr_payload


class TestStockEntryScannerContract(unittest.TestCase):
	def location(self, name, parent="AISLE", location_type="Rack", is_group=0, disabled=0, code=None, warehouse="FG-WH"):
		location = frappe._dict(name=name, location_code=code or name, location_name=name.title(),
			location_type=location_type, parent_storage_location=parent, is_group=is_group, disabled=disabled,
			custom_warehouse=warehouse)
		location.inventory_location_id = name
		location.inventory_location_code = code or name
		location.inventory_location_name = name.title()
		return location

	def test_qr_stock_entry_id_is_normalized(self):
		self.assertEqual(_stock_entry_id("/app/stock-entry/MAT-STE-2026-00001"), "MAT-STE-2026-00001")
		self.assertEqual(_stock_entry_id('{"type":"manufacture_stock_entry","stock_entry_id":"STE-1"}'), "STE-1")

	def test_job_card_qr_is_normalized(self):
		self.assertEqual(_job_card_id("ITEM;20;PC;WO-1;PO-JOB00001"), "PO-JOB00001")
		self.assertEqual(_job_card_id('{"job_card_id":"PO-JOB00002"}'), "PO-JOB00002")

	def test_storage_location_qr_uses_document_name_and_separate_display_code(self):
		location = frappe._dict(
			name="STORAGE-LOCATION-DOC-1",
			location_code="SRSC-STG-AREA",
			location_name="Stock Room Sta Clara Staging Area",
			location_type="Staging Area",
			full_path="Stock Room Sta Clara / Staging Area",
			custom_warehouse="Stockroom - Sta Clara",
			custom_restricted_item="",
			custom_storage_capacity=0,
			is_group=0,
		)
		with patch("qcmc_logic.www.storage_location_qr.frappe.get_doc", return_value=location):
			payload = json.loads(_make_qr_payload(location))
		self.assertEqual(payload, {
			"type": "storage_location",
			"location_id": "STORAGE-LOCATION-DOC-1",
			"warehouse": "Stockroom - Sta Clara",
		})

	def test_create_draft_requires_pull_out_slip(self):
		with patch("qcmc_logic.api.stock_entry_scanner._auth", return_value="Administrator"), patch(
			"frappe.db.exists", return_value=True
		):
			result = create_manufacture_receive_draft("PO-JOB00001", "")
		self.assertEqual(result["error_code"], "PULL_OUT_SLIP_REQUIRED")

	def test_create_draft_remains_draft_and_returns_allocations(self):
		job_card = frappe._dict(name="PO-JOB00001", work_order="WO-1")
		work_order = frappe._dict(name="WO-1")
		doc = SimpleNamespace(
			name="STE-1", stock_entry_type="Manufacture", purpose="Manufacture",
			work_order="WO-1", job_card="", custom_final_job_card="PO-JOB00001",
			custom_reference_document="POS-1", company="Company", docstatus=0,
		)
		doc.items = [frappe._dict(name="FG", is_finished_item=1, t_warehouse="WH")]
		doc.save = lambda **kwargs: None
		doc.get = lambda field: getattr(doc, field, None)
		with patch("qcmc_logic.api.stock_entry_scanner._auth", return_value="Administrator"), patch(
			"frappe.db.exists", return_value=True
		), patch("frappe.get_meta") as meta, patch(
			"frappe.db.sql"
		), patch("frappe.db.get_value", return_value=None), patch(
			"frappe.get_doc", side_effect=[job_card, doc]
		), patch(
			"qcmc_logic.api.stock_entry_scanner._scanner_employee", return_value=None
		), patch(
			"qcmc_logic.api.stock_entry_scanner.user_can_transact_job_card", return_value=True
		), patch(
			"qcmc_logic.api.stock_entry_scanner._get_work_order", return_value=work_order
		), patch(
			"qcmc_logic.api.stock_entry_scanner._can_use_job_card_for_purpose", return_value=True
		), patch(
			"qcmc_logic.api.stock_entry_scanner._pending_qty", return_value=10
		), patch(
			"qcmc_logic.api.stock_entry_scanner._make_manufacture_stock_entry_from_job_card",
			return_value={"name": "STE-1"},
		), patch(
			"qcmc_logic.api.stock_entry_scanner._manufacture_receive_context",
			return_value={"success": True, "stock_entry_id": "STE-1", "docstatus": 0, "status": "Draft"},
		), patch(
			"qcmc_logic.api.stock_entry_scanner._audit_manufacture_draft"
		):
			meta.return_value.has_field.return_value = True
			result = create_manufacture_receive_draft("ITEM;10;PC;WO-1;PO-JOB00001", "POS-1")
		self.assertTrue(result["success"], result)
		self.assertEqual((result["docstatus"], result["status"]), (0, "Draft"))
		self.assertFalse(result["existing_draft"])

	def test_create_draft_rejects_user_without_active_employee(self):
		with patch("qcmc_logic.api.stock_entry_scanner._auth", return_value="scanner@example.com"), patch(
			"frappe.db.get_value", return_value=None
		):
			result = create_manufacture_receive_draft("PO-JOB00001", "POS-1")
		self.assertEqual(result["error_code"], "PERMISSION_DENIED")
		self.assertEqual(
			result["message"],
			"You are not authorized to create Manufacture Draft Stock Entries.",
		)

	def test_custom_stock_entry_type_uses_underlying_purpose(self):
		doc = frappe._dict(stock_entry_type="Custom Manufacture", purpose="Material Receipt")
		with patch("frappe.db.get_value", return_value="Manufacture"):
			self.assertEqual(_purpose(doc), "Manufacture")

	def test_context_excludes_raw_material_rows(self):
		finished = frappe._dict(name="FGROW", item_code="FG", item_name="FG", qty=5, uom="PC", stock_uom="PC", conversion_factor=1, t_warehouse="WH", to_location="")
		doc = frappe._dict(name="STE", stock_entry_type="Manufacture", work_order="WO", company="C")
		with patch("qcmc_logic.api.stock_entry_scanner._auth"), patch(
			"qcmc_logic.api.stock_entry_scanner.ensure_scanner_warehouse_access"
		), patch(
			"qcmc_logic.api.stock_entry_scanner._validate_document", return_value=(doc, [finished])
		), patch("qcmc_logic.api.stock_entry_scanner._purpose", return_value="Manufacture"), patch(
			"qcmc_logic.api.stock_entry_scanner._putaway_allocations", return_value=[]
		), patch(
			"frappe.db.get_value", return_value=frappe._dict(item_name="Finished", has_batch_no=0, has_serial_no=0)
		):
			result = get_manufacture_receive_context("STE")
		self.assertEqual([row["stock_entry_row"] for row in result["finished_items"]], ["FGROW"])
		self.assertEqual(result["work_order_id"], "WO")

	def test_operation_must_be_exact(self):
		with patch("qcmc_logic.api.stock_entry_scanner._auth", return_value="Administrator"):
			result = submit_manufacture_receive("STE", "Material Receipt", "x", [])
		self.assertEqual(result["error_code"], "INVALID_OPERATION")

	def test_item_context_returns_real_uom_and_requirements(self):
		row = frappe._dict(name="ROW", item_code="FG", item_name="", qty=2, uom="Box", stock_uom="PC", conversion_factor=12, t_warehouse="WH", to_location="LOC")
		with patch("frappe.db.get_value", return_value=frappe._dict(item_name="Finished", has_batch_no=1, has_serial_no=0)):
			result = _item_result(row)
		self.assertEqual((result["item_name"], result["uom"], result["conversion_factor"]), ("Finished", "Box", 12))
		self.assertTrue(result["requires_batch"])

	def test_manufacture_receive_uses_exact_putaway_rule_location(self):
		doc = frappe._dict(company="Company")
		row = frappe._dict(item_code="FG", s_warehouse="WIP", t_warehouse="FG-WH", qty=5, transfer_qty=5, conversion_factor=1)
		rule = frappe._dict(name="PUT-1", warehouse="FG-WH", location="RACK-1", free_space=10)
		with patch(
			"qcmc_logic.api.stock_entry_scanner.get_ordered_dimension_putaway_rules",
			return_value=(False, [rule]),
		):
			self.assertEqual(_resolve_finished_item_putaway(doc, row, "RACK-1").name, "PUT-1")
			with self.assertRaises(ScannerAPIError) as mismatch:
				_resolve_finished_item_putaway(doc, row, "RACK-2")
		self.assertEqual(mismatch.exception.code, "INVALID_INVENTORY_LOCATION")

	def test_finished_quantity_is_distributed_by_priority_and_capacity(self):
		doc = frappe._dict(company="Company")
		row = frappe._dict(name="ROW", item_code="FG", item_name="Finished", s_warehouse="WIP", t_warehouse="FG-WH", qty=30, transfer_qty=30, conversion_factor=1, uom="PC", stock_uom="PC")
		rules = [
			frappe._dict(name="P1", warehouse="FG-WH", location="R1", free_space=10, priority=1),
			frappe._dict(name="P2", warehouse="FG-WH", location="R2", free_space=10, priority=2),
			frappe._dict(name="P3", warehouse="FG-WH", location="R3", free_space=10, priority=3),
		]
		def resolve(identity, require_leaf=False, **kwargs):
			if identity == "AISLE": return self.location("AISLE", "", "Aisle", 1)
			return self.location(identity)
		with patch("qcmc_logic.api.stock_entry_scanner.get_ordered_dimension_putaway_rules", return_value=(False, rules)), patch(
			"qcmc_logic.api.stock_entry_scanner._resolve_storage_location", side_effect=resolve
		):
			allocations = _putaway_allocations(doc, row)
		self.assertEqual([(x["inventory_location"], x["quantity"]) for x in allocations], [("R1", 10), ("R2", 10), ("R3", 10)])

	def test_putaway_allocation_uses_location_document_name_not_display_code(self):
		doc = frappe._dict(company="Company")
		row = frappe._dict(name="ROW", item_code="FG", item_name="Finished", s_warehouse="WIP", t_warehouse="FG-WH", qty=10, transfer_qty=10, conversion_factor=1, uom="PC", stock_uom="PC")
		rule = frappe._dict(name="P1", warehouse="FG-WH", location="QR-RACK-2", free_space=10, priority=1)
		resolved = self.location("STORAGE-LOCATION-DOC-2", code="QR-RACK-2", warehouse="FG-WH")
		with patch("qcmc_logic.api.stock_entry_scanner.get_ordered_dimension_putaway_rules", return_value=(False, [rule])), patch(
			"qcmc_logic.api.stock_entry_scanner._resolve_storage_location", return_value=resolved
		):
			allocation = _putaway_allocations(doc, row)[0]
		self.assertEqual(allocation["inventory_location_id"], "STORAGE-LOCATION-DOC-2")
		self.assertEqual(allocation["inventory_location_code"], "QR-RACK-2")

	def test_putaway_rule_and_location_warehouse_must_match(self):
		doc = frappe._dict(company="Company")
		row = frappe._dict(name="ROW", item_code="FG", item_name="Finished", s_warehouse="WIP", t_warehouse="Stockroom - Sta Clara", qty=10, transfer_qty=10, conversion_factor=1, uom="PC", stock_uom="PC")
		rule = frappe._dict(name="P1", warehouse="Stockroom - Sta Clara", location="GUY-R1", free_space=10, priority=1)
		with patch("qcmc_logic.api.stock_entry_scanner.get_ordered_dimension_putaway_rules", return_value=(False, [rule])), patch(
			"qcmc_logic.api.stock_entry_scanner._resolve_storage_location",
			return_value=self.location("GUY-R1", warehouse="Stockroom - Guyong"),
		):
			with self.assertRaises(ScannerAPIError) as error:
				_putaway_allocations(doc, row)
		self.assertEqual(error.exception.code, "PUTAWAY_LOCATION_WAREHOUSE_MISMATCH")

	def test_warehouse_normalization_is_comparison_only(self):
		self.assertEqual(_normalize_warehouse("Stockroom-StaClara"), _normalize_warehouse("Stockroom - Sta Clara"))

	def test_document_rejects_non_draft_and_invalid_purpose(self):
		for docstatus, purpose, code in (
			(1, "Manufacture", "STOCK_ENTRY_NOT_DRAFT"),
			(2, "Manufacture", "STOCK_ENTRY_NOT_DRAFT"),
			(0, "Material Receipt", "INVALID_OPERATION"),
		):
			doc = SimpleNamespace(name="STE", docstatus=docstatus, stock_entry_type=purpose, purpose=purpose, items=[])
			doc.check_permission = lambda permission: None
			with patch("frappe.db.exists", return_value=True), patch("frappe.get_doc", return_value=doc), patch(
				"qcmc_logic.api.stock_entry_scanner._purpose", return_value=purpose
			):
				with self.assertRaises(ScannerAPIError) as error:
					_validate_document("STE")
			self.assertEqual(error.exception.code, code)

	def test_subset_allocations_are_allowed_but_duplicates_are_rejected(self):
		row = frappe._dict(name="ROW", item_code="FG")
		doc = SimpleNamespace(items=[row])
		allocations = [
			{"allocation_id":"A1", "inventory_location":"R1"},
			{"allocation_id":"A2", "inventory_location":"R2"},
		]
		with patch("qcmc_logic.api.stock_entry_scanner._putaway_allocations", return_value=allocations):
			with self.assertRaises(ScannerAPIError) as duplicate:
				_split_finished_rows(doc, [row], [
					{"stock_entry_row":"ROW", "allocation_id":"A1"},
					{"stock_entry_row":"ROW", "allocation_id":"A1"},
				])
		self.assertEqual(duplicate.exception.code, "DUPLICATE_ALLOCATION")

	def test_partial_allocation_quantity_is_accepted(self):
		allocation = {
			"allocation_id": "A1", "stock_entry_row": "ROW", "item_code": "FG",
			"uom": "PC", "stock_uom": "PC", "target_warehouse": "WH-1",
			"inventory_location_id": "R1", "inventory_location": "R1",
			"quantity": 10, "stock_quantity": 10, "conversion_factor": 1,
			"putaway_rule": "PUT-1", "allocation_source": "putaway_rule",
		}
		entry = {"allocation_id": "A1", "stock_entry_row": "ROW", "quantity": 4, "inventory_location_id": "R1"}
		with patch("qcmc_logic.api.stock_entry_scanner._resolve_storage_location", return_value=self.location("R1")):
			location, overridden = _validate_allocation_entry(frappe._dict(), entry, allocation, 1)
		self.assertEqual((location.name, overridden), ("R1", False))
		for quantity, code in ((0, "INVALID_RECEIVE_QUANTITY"), (-1, "INVALID_RECEIVE_QUANTITY"), (11, "RECEIVE_QUANTITY_EXCEEDS_REMAINING")):
			with patch("qcmc_logic.api.stock_entry_scanner._resolve_storage_location", return_value=self.location("R1")):
				with self.assertRaises(ScannerAPIError) as error:
					_validate_allocation_entry(frappe._dict(), {**entry, "quantity": quantity}, allocation, 1)
			self.assertEqual(error.exception.code, code)

	def test_general_purpose_location_is_discovered_and_sorted_dynamically(self):
		locations = [
			frappe._dict(name="R10", location_code="R10", location_name="Rack 10", disabled=0, is_group=0, custom_warehouse="WH-1", custom_restricted_item="", custom_storage_capacity=0),
			frappe._dict(name="R2", location_code="R2", location_name="Rack 2", disabled=0, is_group=0, custom_warehouse="WH-1", custom_restricted_item="", custom_storage_capacity=None),
			frappe._dict(name="OTHER", location_code="OTHER", location_name="Other", disabled=0, is_group=0, custom_warehouse="WH-2", custom_restricted_item="", custom_storage_capacity=0),
			frappe._dict(name="LIMITED", location_code="LIMITED", location_name="Limited", disabled=0, is_group=0, custom_warehouse="WH-1", custom_restricted_item="", custom_storage_capacity=5),
			frappe._dict(name="RESTRICTED", location_code="RESTRICTED", location_name="Restricted", disabled=0, is_group=0, custom_warehouse="WH-1", custom_restricted_item="OTHER", custom_storage_capacity=0),
		]
		meta = SimpleNamespace(has_field=lambda field: False)
		with patch("frappe.get_meta", return_value=meta), patch("frappe.get_all", return_value=locations):
			selected = _general_purpose_location("WH-1")
			self.assertEqual(selected.inventory_location_id, "R2")
			selected = _general_purpose_location("WH-1", [{"inventory_location_id": "R2"}])
			self.assertEqual(selected.inventory_location_id, "R10")

	def test_explicit_rules_precede_one_unlimited_fallback(self):
		doc = frappe._dict(company="Company")
		row = frappe._dict(name="ROW", item_code="FG", item_name="Finished", s_warehouse="WIP", t_warehouse="FG-WH", qty=25, transfer_qty=25, conversion_factor=1, uom="PC", stock_uom="PC")
		rule = frappe._dict(name="P1", warehouse="FG-WH", location="R1", free_space=10, priority=1)
		fallback = self.location("GENERAL", warehouse="FG-WH")
		fallback.putaway_priority = 1000
		with patch("qcmc_logic.api.stock_entry_scanner.get_ordered_dimension_putaway_rules", return_value=(False, [rule])), patch(
			"qcmc_logic.api.stock_entry_scanner._resolve_storage_location", side_effect=lambda identity, require_leaf=False, **kwargs: self.location(identity, warehouse="FG-WH")
		), patch("qcmc_logic.api.stock_entry_scanner._general_purpose_location", return_value=fallback):
			allocations = _putaway_allocations(doc, row)
		self.assertEqual([(a["inventory_location_id"], a["quantity"], a["allocation_source"]) for a in allocations], [
			("R1", 10, "putaway_rule"), ("GENERAL", 15, "general_purpose_location")
		])

	def test_idempotent_replay_and_changed_payload_conflict(self):
		record = frappe._dict(request_hash="same", result_json=json.dumps({"success": True, "stock_entry_id": "STE"}))
		with patch("frappe.db.get_value", return_value=record):
			result = _get_idempotent_replay("uuid", "same")
			self.assertTrue(result["duplicate_submission"])
			with self.assertRaises(ScannerAPIError) as conflict:
				_get_idempotent_replay("uuid", "different")
			self.assertEqual(conflict.exception.code, "SUBMISSION_ID_CONFLICT")

	def test_allocation_validation_rejects_wrong_location_warehouse_quantity_and_id(self):
		allocation = {
			"allocation_id": "ROW:RULE:R1", "item_code": "FG", "uom": "PC",
			"target_warehouse": "Stockroom - Sta Clara", "inventory_location": "R1", "quantity": 10,
			"stock_quantity": 10, "stock_uom": "PC", "conversion_factor": 1,
			"putaway_rule": "RULE", "allocation_source": "putaway_rule",
		}
		valid = {**allocation, "target_warehouse": "Stockroom-StaClara"}
		allocation["inventory_location_id"] = "R1"
		with patch("qcmc_logic.api.stock_entry_scanner._resolve_storage_location", side_effect=lambda value, require_leaf=False: self.location(value)):
			_validate_allocation_entry(frappe._dict(company="Company"), valid, allocation, 1)
			for field, value, code in (
				("allocation_id", "WRONG", "ALLOCATION_NOT_FOUND"),
				("item_code", "OTHER", "ITEM_MISMATCH"),
				("uom", "BOX", "UOM_MISMATCH"),
				("quantity", 11, "RECEIVE_QUANTITY_EXCEEDS_REMAINING"),
			):
				with self.assertRaises(ScannerAPIError) as error:
					_validate_allocation_entry(frappe._dict(company="Company"), {**valid, field: value}, allocation, 1)
				self.assertEqual(error.exception.code, code)

	def test_valid_location_override_uses_direct_location_configuration(self):
		doc = frappe._dict(company="Company")
		allocation = {
			"allocation_id": "A1", "stock_entry_row": "ROW", "item_code": "FG", "uom": "PC",
			"stock_uom": "PC", "target_warehouse": "Stockroom - Sta Clara",
			"inventory_location_id": "R1", "quantity": 10, "stock_quantity": 10,
		}
		entry = {"allocation_id":"A1", "stock_entry_row":"ROW", "item_code":"FG", "uom":"PC", "quantity":10, "inventory_location_id":"R2"}
		with patch("qcmc_logic.api.stock_entry_scanner._resolve_storage_location", side_effect=lambda value, require_leaf=False: self.location(value)), patch(
			"frappe.db.get_value", return_value=frappe._dict(custom_warehouse="Stockroom-StaClara", custom_restricted_item="", custom_storage_capacity=25)
		), patch("qcmc_logic.api.stock_entry_scanner.get_dimension_stock_balance", return_value=5):
			location, overridden = _validate_allocation_entry(doc, entry, allocation, 1, reserved_stock_qty=5)
		self.assertEqual((location.inventory_location_id, overridden), ("R2", True))

	def test_override_rejects_wrong_warehouse_item_and_insufficient_capacity(self):
		allocation = {"item_code":"FG", "target_warehouse":"WH-1", "stock_quantity":10, "stock_uom":"PC"}
		location = self.location("R2")
		cases = (
			(frappe._dict(custom_warehouse="WH-2", custom_restricted_item="", custom_storage_capacity=20), 0, "LOCATION_WAREHOUSE_MISMATCH"),
			(frappe._dict(custom_warehouse="WH-1", custom_restricted_item="OTHER", custom_storage_capacity=20), 0, "LOCATION_ITEM_MISMATCH"),
			(frappe._dict(custom_warehouse="WH-1", custom_restricted_item="", custom_storage_capacity=10), 5, "INSUFFICIENT_PUTAWAY_CAPACITY"),
		)
		for location_data, balance, code in cases:
			with patch("frappe.db.get_value", return_value=location_data), patch(
				"qcmc_logic.api.stock_entry_scanner.get_dimension_stock_balance", return_value=balance
			):
				with self.assertRaises(ScannerAPIError) as error:
					_validate_override_location(allocation, location)
			self.assertEqual(error.exception.code, code)

	def test_unrestricted_location_without_putaway_rule_accepts_item(self):
		allocation = {"item_code":"ANY-ITEM", "target_warehouse":"WH-1", "stock_quantity":10, "stock_uom":"PC"}
		location = self.location("NO-RULE-RACK")
		location_data = frappe._dict(custom_warehouse="WH-1", custom_restricted_item="", custom_storage_capacity=100)
		with patch("frappe.db.get_value", return_value=location_data), patch(
			"qcmc_logic.api.stock_entry_scanner.get_dimension_stock_balance", return_value=20
		), patch("frappe.get_all") as putaway_query:
			_validate_override_location(allocation, location)
		putaway_query.assert_not_called()

	def test_matching_item_restriction_is_accepted_and_missing_warehouse_is_clear(self):
		allocation = {"item_code":"FG", "target_warehouse":"WH-1", "stock_quantity":10, "stock_uom":"PC"}
		location = self.location("R1")
		with patch("frappe.db.get_value", return_value=frappe._dict(custom_warehouse="WH-1", custom_restricted_item="FG", custom_storage_capacity=0)), patch(
			"qcmc_logic.api.stock_entry_scanner.get_dimension_stock_balance", return_value=0
		):
			_validate_override_location(allocation, location)
		with patch("frappe.db.get_value", return_value=frappe._dict(custom_warehouse="", custom_restricted_item="", custom_storage_capacity=0)):
			with self.assertRaises(ScannerAPIError) as error:
				_validate_override_location(allocation, location)
		self.assertEqual(error.exception.code, "STORAGE_LOCATION_WAREHOUSE_REQUIRED")

	def test_blank_and_zero_override_capacity_are_unlimited(self):
		allocation = {"item_code":"FG", "target_warehouse":"WH-1", "stock_quantity":10000, "stock_uom":"PC"}
		location = self.location("UNLIMITED-RACK")
		for capacity in (None, "", 0):
			location_data = frappe._dict(custom_warehouse="WH-1", custom_restricted_item="", custom_storage_capacity=capacity)
			with patch("frappe.db.get_value", return_value=location_data), patch(
				"qcmc_logic.api.stock_entry_scanner.get_dimension_stock_balance", return_value=50000
			):
				_validate_override_location(allocation, location, reserved_stock_qty=25000)

	def test_positive_override_capacity_includes_existing_and_reserved_stock(self):
		allocation = {"item_code":"FG", "target_warehouse":"WH-1", "stock_quantity":10000, "stock_uom":"PC"}
		location = self.location("LIMITED-RACK")
		location_data = frappe._dict(custom_warehouse="WH-1", custom_restricted_item="", custom_storage_capacity=20000)
		with patch("frappe.db.get_value", return_value=location_data), patch(
			"qcmc_logic.api.stock_entry_scanner.get_dimension_stock_balance", return_value=5000
		):
			_validate_override_location(allocation, location, reserved_stock_qty=5000)
			with self.assertRaises(ScannerAPIError) as error:
				_validate_override_location(allocation, location, reserved_stock_qty=5001)
		self.assertEqual(error.exception.code, "INSUFFICIENT_PUTAWAY_CAPACITY")

	def test_location_uses_document_name_as_identity_and_legacy_code_is_explicit(self):
		resolved = self.location("Storage Location DB Name", code="QR-RACK-2")
		with patch("frappe.db.get_value", return_value=resolved), patch("frappe.get_all") as code_query:
			location = _resolve_storage_location(" Storage Location DB Name ", require_leaf=True)
		self.assertEqual(location.inventory_location_id, "Storage Location DB Name")
		self.assertEqual(location.inventory_location_code, "QR-RACK-2")
		code_query.assert_not_called()
		with patch("frappe.db.get_value", return_value=None), patch("frappe.get_all", return_value=[resolved]):
			legacy = _resolve_storage_location("QR-RACK-2", require_leaf=True, allow_legacy_code=True)
		self.assertEqual(legacy.inventory_location_id, "Storage Location DB Name")
		with patch("frappe.db.get_value", return_value=None), patch("frappe.get_all", return_value=[resolved, self.location("OTHER", code="QR-RACK-2")]):
			with self.assertRaises(ScannerAPIError) as ambiguous:
				_resolve_storage_location("QR-RACK-2", allow_legacy_code=True)
		self.assertEqual(ambiguous.exception.code, "PUTAWAY_LOCATION_AMBIGUOUS")
		with patch("frappe.db.get_value", return_value=None), patch("frappe.get_all", return_value=[]):
			with self.assertRaises(ScannerAPIError) as missing:
				_resolve_storage_location("MISSING", allow_legacy_code=True)
		self.assertEqual(missing.exception.code, "PUTAWAY_LOCATION_NOT_FOUND")
		with patch("frappe.db.get_value", return_value=self.location("R1", disabled=1)):
			with self.assertRaises(ScannerAPIError): _resolve_storage_location("R1")

	def test_parent_distribution_requires_one_item_parent_and_exact_total(self):
		row = frappe._dict(item_code="FG", t_warehouse="FG-WH", uom="PC", qty=20)
		allocations = [
			{"item_code":"FG", "target_warehouse":"FG-WH", "uom":"PC", "quantity":10, "putaway_rule":"P1", "parent_location_name":"AISLE"},
			{"item_code":"FG", "target_warehouse":"FG-WH", "uom":"PC", "quantity":10, "putaway_rule":"P2", "parent_location_name":"AISLE"},
		]
		with patch("qcmc_logic.api.stock_entry_scanner._resolve_storage_location", return_value=self.location("AISLE", "", "Aisle", 1)):
			mode, parent = _parent_distribution([row], allocations)
			self.assertEqual((mode, parent["location_id"]), ("parent_location", "AISLE"))
			self.assertEqual(_parent_distribution([row], [{**allocations[0], "quantity":9}])[0], "exact_location")
			self.assertEqual(_parent_distribution([row], [allocations[0], {**allocations[1], "parent_location_name":"OTHER"}])[0], "exact_location")
			self.assertEqual(_parent_distribution([row], [allocations[0], {**allocations[1], "item_code":"OTHER"}])[0], "exact_location")

	def test_scanned_parent_must_match_every_submitted_child(self):
		parent = {"location_id": "AISLE"}
		with patch("qcmc_logic.api.stock_entry_scanner._resolve_storage_location", side_effect=lambda value: self.location(value, "", "Aisle", 1)):
			_validate_distribution_parent("parent_location", parent, [{"parent_location_id":"AISLE"}])
			with self.assertRaises(ScannerAPIError):
				_validate_distribution_parent("parent_location", parent, [{"parent_location_id":"OTHER"}])
			with self.assertRaises(ScannerAPIError):
				_validate_distribution_parent("parent_location", parent, [{"parent_location_id":"AISLE"}, {"parent_location_id":"OTHER"}])

	# Tests for request_id-based idempotency (requirement 1)
	def test_request_id_is_required(self):
		"""Requirement 1: request_id is required for idempotency."""
		with patch("qcmc_logic.api.stock_entry_scanner._auth", return_value="Administrator"), patch(
			"frappe.db.exists", return_value=True
		):
			result = create_manufacture_receive_draft("PO-JOB00001", "POS-1", request_id="")
		self.assertEqual(result["error_code"], "REQUEST_ID_REQUIRED")
		self.assertFalse(result["success"])

	def test_first_request_creates_new_draft(self):
		"""Requirement 1: First request with new request_id creates a new Draft Stock Entry."""
		job_card = frappe._dict(name="PO-JOB00001", work_order="WO-1")
		work_order = frappe._dict(name="WO-1")
		doc = SimpleNamespace(
			name="MAT-STE-00001", stock_entry_type="Manufacture", purpose="Manufacture",
			work_order="WO-1", job_card="", custom_final_job_card="PO-JOB00001",
			custom_reference_document="PULL-OUT-001", company="Company", docstatus=0,
		)
		doc.items = [frappe._dict(name="FG", is_finished_item=1, t_warehouse="WH")]
		doc.save = lambda **kwargs: None
		doc.get = lambda field: getattr(doc, field, None)
		
		with patch("qcmc_logic.api.stock_entry_scanner._auth", return_value="Administrator"), patch(
			"frappe.db.exists", return_value=True
		), patch("frappe.get_meta") as meta, patch(
			"frappe.db.sql"
		), patch("frappe.db.get_value", return_value=None), patch(
			"frappe.get_doc", side_effect=[job_card, doc]
		), patch(
			"qcmc_logic.api.stock_entry_scanner._scanner_employee", return_value=None
		), patch(
			"qcmc_logic.api.stock_entry_scanner.user_can_transact_job_card", return_value=True
		), patch(
			"qcmc_logic.api.stock_entry_scanner._get_work_order", return_value=work_order
		), patch(
			"qcmc_logic.api.stock_entry_scanner._can_use_job_card_for_purpose", return_value=True
		), patch(
			"qcmc_logic.api.stock_entry_scanner._pending_qty", return_value=10000
		), patch(
			"qcmc_logic.api.stock_entry_scanner._make_manufacture_stock_entry_from_job_card",
			return_value={"name": "MAT-STE-00001"},
		), patch(
			"qcmc_logic.api.stock_entry_scanner._manufacture_receive_context",
			return_value={"success": True, "stock_entry_id": "MAT-STE-00001", "docstatus": 0, "status": "Draft"},
		), patch(
			"qcmc_logic.api.stock_entry_scanner._audit_manufacture_draft"
		), patch(
			"qcmc_logic.api.warehouse_workflow.finish_request", side_effect=lambda req, resp: {**resp, "request_id": "uuid-request-1"}
		):
			meta.return_value.has_field.return_value = True
			result = create_manufacture_receive_draft(
				"PO-JOB00001", 
				"PULL-OUT-001",
				quantity=10000,
				request_id="550e8400-e29b-41d4-a716-446655440000"
			)
		self.assertTrue(result["success"], result)
		self.assertEqual(result["stock_entry_id"], "MAT-STE-00001")
		self.assertEqual(result["docstatus"], 0)
		self.assertEqual(result["status"], "Draft")
		self.assertFalse(result["duplicate_request"])
		self.assertFalse(result["existing_draft"])

	def test_retry_same_request_id_returns_same_draft(self):
		"""Requirement 1: Retrying with same request_id returns same Stock Entry without creating duplicate."""
		# This is handled by begin_request/finish_request, which stores the response
		request_id = "550e8400-e29b-41d4-a716-446655440000"
		cached_response = {
			"success": True,
			"stock_entry_id": "MAT-STE-00001",
			"docstatus": 0,
			"status": "Draft",
			"duplicate_request": False,
			"existing_draft": False,
			"request_id": request_id,
		}
		
		with patch("qcmc_logic.api.stock_entry_scanner._auth", return_value="Administrator"), patch(
			"qcmc_logic.api.warehouse_workflow.begin_request", return_value=frappe._dict(
				name=request_id,
				replay={**cached_response, "duplicate_request": True},
			)
		):
			result = create_manufacture_receive_draft(
				"PO-JOB00001",
				"PULL-OUT-001",
				quantity=10000,
				request_id=request_id
			)
		self.assertTrue(result["success"])
		self.assertEqual(result["stock_entry_id"], "MAT-STE-00001")
		self.assertTrue(result["duplicate_request"])

	def test_new_request_id_creates_separate_draft_for_same_job_card(self):
		"""Requirement 1 & 4: New request_id creates separate Draft even for same Job Card."""
		job_card = frappe._dict(name="PO-JOB00001", work_order="WO-1")
		work_order = frappe._dict(name="WO-1")
		# First request creates MAT-STE-00001
		# Second request should create MAT-STE-00002
		doc = SimpleNamespace(
			name="MAT-STE-00002", stock_entry_type="Manufacture", purpose="Manufacture",
			work_order="WO-1", job_card="", custom_final_job_card="PO-JOB00001",
			custom_reference_document="PULL-OUT-002", company="Company", docstatus=0,
		)
		doc.items = [frappe._dict(name="FG", is_finished_item=1, t_warehouse="WH")]
		doc.save = lambda **kwargs: None
		doc.get = lambda field: getattr(doc, field, None)
		
		with patch("qcmc_logic.api.stock_entry_scanner._auth", return_value="Administrator"), patch(
			"frappe.db.exists", return_value=True
		), patch("frappe.get_meta") as meta, patch(
			"frappe.db.sql"
		), patch("frappe.db.get_value", return_value=None), patch(
			"frappe.get_doc", side_effect=[job_card, doc]
		), patch(
			"qcmc_logic.api.stock_entry_scanner._scanner_employee", return_value=None
		), patch(
			"qcmc_logic.api.stock_entry_scanner.user_can_transact_job_card", return_value=True
		), patch(
			"qcmc_logic.api.stock_entry_scanner._get_work_order", return_value=work_order
		), patch(
			"qcmc_logic.api.stock_entry_scanner._can_use_job_card_for_purpose", return_value=True
		), patch(
			"qcmc_logic.api.stock_entry_scanner._pending_qty", return_value=15000
		), patch(
			"qcmc_logic.api.stock_entry_scanner._make_manufacture_stock_entry_from_job_card",
			return_value={"name": "MAT-STE-00002"},
		), patch(
			"qcmc_logic.api.stock_entry_scanner._manufacture_receive_context",
			return_value={"success": True, "stock_entry_id": "MAT-STE-00002", "docstatus": 0, "status": "Draft"},
		), patch(
			"qcmc_logic.api.stock_entry_scanner._audit_manufacture_draft"
		), patch(
			"qcmc_logic.api.warehouse_workflow.finish_request", side_effect=lambda req, resp: {**resp, "request_id": "uuid-request-2"}
		):
			meta.return_value.has_field.return_value = True
			result = create_manufacture_receive_draft(
				"PO-JOB00001",
				"PULL-OUT-002",
				quantity=5000,
				request_id="650e8400-e29b-41d4-a716-446655440001"
			)
		self.assertTrue(result["success"])
		self.assertEqual(result["stock_entry_id"], "MAT-STE-00002")
		self.assertFalse(result["duplicate_request"])
		self.assertFalse(result["existing_draft"])

	def test_quantity_validation_rejects_zero_and_negative(self):
		"""Requirement 3: Quantity must be greater than zero."""
		with patch("qcmc_logic.api.stock_entry_scanner._auth", return_value="Administrator"), patch(
			"frappe.db.exists", return_value=True
		):
			for qty in [0, -1, -100]:
				result = create_manufacture_receive_draft(
					"PO-JOB00001",
					"PULL-OUT-001",
					quantity=qty,
					request_id="550e8400-e29b-41d4-a716-446655440000"
				)
				self.assertEqual(result["error_code"], "INVALID_QUANTITY")

	def test_quantity_validation_rejects_exceeding_receivable(self):
		"""Requirement 3: Quantity must not exceed legally receivable quantity."""
		job_card = frappe._dict(name="PO-JOB00001", work_order="WO-1")
		work_order = frappe._dict(name="WO-1")
		
		with patch("qcmc_logic.api.stock_entry_scanner._auth", return_value="Administrator"), patch(
			"frappe.db.exists", return_value=True
		), patch("frappe.get_meta") as meta, patch(
			"frappe.db.sql"
		), patch("frappe.db.get_value", return_value=None), patch(
			"frappe.get_doc", return_value=job_card
		), patch(
			"qcmc_logic.api.stock_entry_scanner._scanner_employee", return_value=None
		), patch(
			"qcmc_logic.api.stock_entry_scanner.user_can_transact_job_card", return_value=True
		), patch(
			"qcmc_logic.api.stock_entry_scanner._get_work_order", return_value=work_order
		), patch(
			"qcmc_logic.api.stock_entry_scanner._can_use_job_card_for_purpose", return_value=True
		), patch(
			"qcmc_logic.api.stock_entry_scanner._pending_qty", return_value=10000
		):
			meta.return_value.has_field.return_value = True
			result = create_manufacture_receive_draft(
				"PO-JOB00001",
				"PULL-OUT-001",
				quantity=15000,  # exceeds remaining 10000
				request_id="550e8400-e29b-41d4-a716-446655440000"
			)
		self.assertEqual(result["error_code"], "QUANTITY_EXCEEDS_RECEIVABLE")

	def test_request_id_payload_mismatch_rejected(self):
		"""Requirement 6: Reusing request_id with different payload is rejected."""
		request_id = "550e8400-e29b-41d4-a716-446655440000"
		
		with patch("qcmc_logic.api.stock_entry_scanner._auth", return_value="Administrator"), patch(
			"qcmc_logic.api.warehouse_workflow.begin_request", side_effect=frappe.ValidationError("DUPLICATE_TRANSACTION", "This request ID was already used with different content.")
		):
			result = create_manufacture_receive_draft(
				"PO-JOB00001",
				"PULL-OUT-001",
				quantity=5000,  # different from first request
				request_id=request_id
			)
		self.assertEqual(result["error_code"], "ERP_VALIDATION_FAILED")

	def test_draft_status_preserved(self):
		"""Requirement 4: All created Stock Entries must remain Draft."""
		job_card = frappe._dict(name="PO-JOB00001", work_order="WO-1")
		work_order = frappe._dict(name="WO-1")
		doc = SimpleNamespace(
			name="MAT-STE-00001", stock_entry_type="Manufacture", purpose="Manufacture",
			work_order="WO-1", job_card="", custom_final_job_card="PO-JOB00001",
			custom_reference_document="PULL-OUT-001", company="Company", docstatus=0,
		)
		doc.items = [frappe._dict(name="FG", is_finished_item=1, t_warehouse="WH")]
		doc.save = lambda **kwargs: None
		doc.get = lambda field: getattr(doc, field, None)
		
		with patch("qcmc_logic.api.stock_entry_scanner._auth", return_value="Administrator"), patch(
			"frappe.db.exists", return_value=True
		), patch("frappe.get_meta") as meta, patch(
			"frappe.db.sql"
		), patch("frappe.db.get_value", return_value=None), patch(
			"frappe.get_doc", side_effect=[job_card, doc]
		), patch(
			"qcmc_logic.api.stock_entry_scanner._scanner_employee", return_value=None
		), patch(
			"qcmc_logic.api.stock_entry_scanner.user_can_transact_job_card", return_value=True
		), patch(
			"qcmc_logic.api.stock_entry_scanner._get_work_order", return_value=work_order
		), patch(
			"qcmc_logic.api.stock_entry_scanner._can_use_job_card_for_purpose", return_value=True
		), patch(
			"qcmc_logic.api.stock_entry_scanner._pending_qty", return_value=10000
		), patch(
			"qcmc_logic.api.stock_entry_scanner._make_manufacture_stock_entry_from_job_card",
			return_value={"name": "MAT-STE-00001"},
		), patch(
			"qcmc_logic.api.stock_entry_scanner._manufacture_receive_context",
			return_value={"success": True, "stock_entry_id": "MAT-STE-00001", "docstatus": 0, "status": "Draft"},
		), patch(
			"qcmc_logic.api.stock_entry_scanner._audit_manufacture_draft"
		), patch(
			"qcmc_logic.api.warehouse_workflow.finish_request", side_effect=lambda req, resp: {**resp, "request_id": "uuid-request-1"}
		):
			meta.return_value.has_field.return_value = True
			result = create_manufacture_receive_draft(
				"PO-JOB00001",
				"PULL-OUT-001",
				quantity=10000,
				request_id="550e8400-e29b-41d4-a716-446655440000"
			)
		# Verify that docstatus is 0 and status is Draft
		self.assertEqual(result["docstatus"], 0)
		self.assertEqual(result["status"], "Draft")


class TestUpdateManufactureReceiveDraft(unittest.TestCase):
	request_id = "550e8400-e29b-41d4-a716-446655440000"

	def setUp(self):
		self.row = frappe._dict(
			name="ROW-1", item_code="FG-001", uom="PCS", qty=10,
			transfer_qty=10, conversion_factor=1,
		)
		self.doc = SimpleNamespace(
			name="MAT-STE-00001", docstatus=0, modified="2026-09-04 10:00:00",
			stock_entry_type="Manufacture", purpose="Manufacture", items=[self.row],
		)
		self.doc.save = lambda **kwargs: None
		self.batch = frappe._dict(
			name="HANDOVER-001", status="PENDING_CHECK",
			source_stock_entries=[frappe._dict(
				stock_entry=self.doc.name, stock_entry_row=self.row.name,
				item=self.row.item_code,
			)],
		)
		self.batch.save = lambda **kwargs: None

	def call(self, row=None, doc=None):
		row = row or {"stock_entry_id": self.doc.name, "stock_entry_row": self.row.name,
			"item_code": self.row.item_code, "quantity": 20, "uom": self.row.uom}
		doc = doc or self.doc
		with patch("qcmc_logic.api.stock_entry_scanner._auth", return_value="warehouse@example.com"), patch(
			"qcmc_logic.api.stock_entry_scanner._validate_document", return_value=(doc, [self.row])
		), patch("qcmc_logic.api.stock_entry_scanner.ensure_scanner_warehouse_access"), patch("frappe.db.exists", return_value=True), patch(
			"frappe.get_doc", return_value=self.batch
		), patch("qcmc_logic.api.warehouse_workflow.begin_request", return_value=frappe._dict(
			name=self.request_id, operation="update_manufacture_receive_draft", request_hash="hash",
			request_json="{}", user="warehouse@example.com", replay=None,
		)), patch("qcmc_logic.api.warehouse_workflow.finish_request", side_effect=lambda request, response: response):
			return update_manufacture_receive_draft(
				self.batch.name, self.request_id, [row], device_id="SCANNER-1"
			)

	def test_successful_update_without_checker_role(self):
		result = self.call()
		self.assertTrue(result["success"])
		self.assertEqual(result["status"], "Draft")
		self.assertEqual(result["items"][0]["verified_quantity"], 20)
		self.assertEqual(self.row.qty, 20)
		self.assertEqual(self.doc.docstatus, 0)
		self.assertEqual(self.batch.source_stock_entries[0].verified_quantity, 20)

	def test_only_submitted_row_is_updated(self):
		other_row = frappe._dict(
			name="ROW-2", item_code="FG-002", uom="PCS", qty=30,
			transfer_qty=30, conversion_factor=1,
		)
		self.doc.items.append(other_row)
		self.batch.source_stock_entries.append(frappe._dict(
			stock_entry=self.doc.name, stock_entry_row=other_row.name,
			item=other_row.item_code, verified_quantity=30,
		))
		result = self.call()
		self.assertTrue(result["success"])
		self.assertEqual(self.row.qty, 20)
		self.assertEqual(other_row.qty, 30)
		self.assertEqual(self.batch.source_stock_entries[1].verified_quantity, 30)

	def test_rejects_submitted_stock_entry(self):
		self.doc.docstatus = 1
		with patch("qcmc_logic.api.stock_entry_scanner._auth", return_value="warehouse@example.com"), patch(
			"qcmc_logic.api.stock_entry_scanner._validate_document",
			side_effect=ScannerAPIError("STOCK_ENTRY_NOT_DRAFT", "not Draft"),
		), patch("qcmc_logic.api.stock_entry_scanner.ensure_scanner_warehouse_access"), patch("frappe.db.exists", return_value=True), patch("frappe.get_doc", return_value=self.batch), patch(
			"qcmc_logic.api.warehouse_workflow.begin_request", return_value=frappe._dict(replay=None)
		):
			result = update_manufacture_receive_draft(self.batch.name, self.request_id, [{
				"stock_entry_id": self.doc.name, "stock_entry_row": self.row.name,
				"item_code": self.row.item_code, "quantity": 20, "uom": self.row.uom,
			}])
		self.assertEqual(result["error_code"], "STOCK_ENTRY_NOT_DRAFT")

	def test_rejects_row_from_another_stock_entry(self):
		result = self.call({"stock_entry_id": "OTHER-STE", "stock_entry_row": "ROW-1",
			"item_code": "FG-001", "quantity": 20, "uom": "PCS"})
		self.assertEqual(result["error_code"], "ROW_NOT_IN_BATCH")

	def test_rejects_mismatched_item_or_uom(self):
		for field, value, code in (("item_code", "OTHER", "ITEM_MISMATCH"), ("uom", "KG", "UOM_MISMATCH")):
			row = {"stock_entry_id": self.doc.name, "stock_entry_row": self.row.name,
				"item_code": self.row.item_code, "quantity": 20, "uom": self.row.uom}
			row[field] = value
			result = self.call(row)
			self.assertEqual(result["error_code"], code)

	def test_rejects_negative_quantity(self):
		result = self.call({"stock_entry_id": self.doc.name, "stock_entry_row": self.row.name,
			"item_code": self.row.item_code, "quantity": -1, "uom": self.row.uom})
		self.assertEqual(result["error_code"], "INVALID_QUANTITY")

	def test_idempotent_replay_does_not_save_again(self):
		replay = {"success": True, "status": "Draft", "items": [], "duplicate_request": True}
		with patch("qcmc_logic.api.stock_entry_scanner._auth", return_value="warehouse@example.com"), patch(
			"qcmc_logic.api.warehouse_workflow.begin_request", return_value=frappe._dict(replay=replay)
		):
			result = update_manufacture_receive_draft(self.batch.name, self.request_id, [{
				"stock_entry_id": self.doc.name, "stock_entry_row": self.row.name,
				"item_code": self.row.item_code, "quantity": 20, "uom": self.row.uom,
			}])
		self.assertTrue(result["duplicate_request"])
		self.assertEqual(self.doc.docstatus, 0)


def run_test_suite():
	suite = unittest.defaultTestLoader.loadTestsFromTestCase(TestStockEntryScannerContract)
	result = unittest.TextTestRunner(verbosity=2).run(suite)
	if not result.wasSuccessful():
		raise AssertionError("Stock Entry scanner contract tests failed")
	return {"tests_run": result.testsRun}
