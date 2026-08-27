from unittest import TestCase

from qcmc_logic.qcmc_logics.doctype.storage_location.storage_location import (
	_relative_path_segment,
	natural_location_sort_key,
	normalize_location_code,
)


class TestStorageLocationPaths(TestCase):
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
