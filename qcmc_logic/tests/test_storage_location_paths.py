from unittest import TestCase
from unittest.mock import MagicMock, patch

from qcmc_logic.qcmc_logics.doctype.storage_location.storage_location import (
	_relative_path_segment,
	_get_warehouse_allocation_location_balances,
	_get_warehouse_allocation_location_details,
	natural_location_sort_key,
	normalize_location_code,
	update_storage_location_from_tree,
)


class TestStorageLocationPaths(TestCase):
	@patch("frappe.db.sql", return_value=[])
	def test_item_balances_use_only_completed_verified_allocations(self, sql):
		_get_warehouse_allocation_location_balances("LOC-1", "FG - Guyong")
		query, parameters = sql.call_args.args[:2]
		self.assertIn("`tabWarehouse Allocation Location`", query)
		self.assertIn("wa.docstatus = 1", query)
		self.assertIn("wa.status = 'Completed'", query)
		self.assertIn("wal.status = 'VERIFIED'", query)
		self.assertIn("se.docstatus = 1", query)
		self.assertEqual(
			parameters,
			{"warehouse": "FG - Guyong", "storage_location": "LOC-1"},
		)

	@patch("frappe.db.sql", return_value=[])
	def test_item_balance_details_include_allocation_audit_fields(self, sql):
		_get_warehouse_allocation_location_details("LOC-1", "FG - Guyong")
		query, parameters = sql.call_args.args[:2]
		for field in (
			"warehouse_allocation",
			"source_document",
			"allocated_by",
			"scanner_id",
			"scan_time",
			"completed_at",
		):
			self.assertIn(field, query)
		self.assertIn("wa.status = 'Completed'", query)
		self.assertIn("wal.status = 'VERIFIED'", query)
		self.assertEqual(parameters["storage_location"], "LOC-1")

	def test_location_code_is_normalized_for_rename(self):
		self.assertEqual(normalize_location_code(" sdw1 staging "), "SDW1-STAGING")
		self.assertEqual(normalize_location_code("GB9_MEZ1"), "GB9_MEZ1")

	def test_location_names_use_natural_numeric_order(self):
		locations = ["COLUMN 1", "COLUMN 10", "COLUMN 2", "COLUMN 20", "COLUMN 3"]
		self.assertEqual(
			sorted(locations, key=natural_location_sort_key),
			["COLUMN 1", "COLUMN 2", "COLUMN 3", "COLUMN 10", "COLUMN 20"],
		)

	def test_repeated_parent_name_is_removed(self):
		self.assertEqual(
			_relative_path_segment(
				"GUYONG BUILDING 9 GROUND FLOOR",
				"GUYONG BUILDING 9",
			),
			"GROUND FLOOR",
		)
		self.assertEqual(
			_relative_path_segment(
				"GUYONG BUILDING 9 GROUND FLOOR BLOCK 3 LOT 26",
				"GUYONG BUILDING 9 GROUND FLOOR BLOCK 3",
			),
			"LOT 26",
		)

	def test_distinct_child_name_is_preserved(self):
		self.assertEqual(_relative_path_segment("LOT 26", "BLOCK 3"), "LOT 26")

	def test_repeated_building_prefix_is_removed(self):
		self.assertEqual(
			_relative_path_segment(
				"GUYONG BUILDING 9 STAGING AREA",
				"GUYONG BUILDING 9 GROUND FLOOR",
			),
			"STAGING AREA",
		)

	@patch("frappe.model.rename_doc.rename_doc")
	@patch("qcmc_logic.qcmc_logics.doctype.storage_location.storage_location.refresh_storage_location_qr_payloads")
	@patch("qcmc_logic.qcmc_logics.doctype.storage_location.storage_location.refresh_storage_location_paths")
	def test_tree_update_saves_all_editable_fields(self, refresh_paths, refresh_qr, rename_doc):
		doc = MagicMock(name="storage-location-document")
		doc.name = "LOC-1"
		with (
			patch("frappe.has_permission", return_value=True),
			patch("frappe.db.exists", return_value=True),
			patch("frappe.get_doc", return_value=doc),
		):
			result = update_storage_location_from_tree(
				"LOC-1", " loc-1 ", "Cube 1", "Cube", "FG - Guyong", 0
			)

		rename_doc.assert_not_called()
		self.assertEqual(doc.location_code, "LOC-1")
		self.assertEqual(doc.location_name, "Cube 1")
		self.assertEqual(doc.location_type, "Cube")
		self.assertEqual(doc.custom_warehouse, "FG - Guyong")
		self.assertEqual(doc.is_group, 0)
		doc.save.assert_called_once_with()
		refresh_paths.assert_called_once_with()
		refresh_qr.assert_called_once_with()
		self.assertEqual(result["name"], "LOC-1")

	@patch("frappe.model.rename_doc.rename_doc", return_value="LOC-2")
	@patch("qcmc_logic.qcmc_logics.doctype.storage_location.storage_location.refresh_storage_location_qr_payloads")
	@patch("qcmc_logic.qcmc_logics.doctype.storage_location.storage_location.refresh_storage_location_paths")
	def test_tree_update_renames_canonical_code(self, refresh_paths, refresh_qr, rename_doc):
		doc = MagicMock(name="storage-location-document")
		doc.name = "LOC-2"
		with (
			patch("frappe.has_permission", return_value=True),
			patch("frappe.db.exists", return_value=True),
			patch("frappe.get_doc", return_value=doc),
		):
			result = update_storage_location_from_tree(
				"LOC-1", "loc-2", "Cube 2", "Cube", "FG - Guyong", 1
			)

		rename_doc.assert_called_once_with("Storage Location", "LOC-1", "LOC-2")
		self.assertEqual(doc.location_code, "LOC-2")
		self.assertEqual(doc.is_group, 1)
		self.assertEqual(result["name"], "LOC-2")
