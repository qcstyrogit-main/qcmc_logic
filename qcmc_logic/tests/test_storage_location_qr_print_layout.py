from pathlib import Path
import unittest


class TestStorageLocationQRPrintLayout(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.template = (
			Path(__file__).parents[1] / "www" / "storage_location_qr.html"
		).read_text(encoding="utf-8")

	def test_print_labels_have_no_visual_container(self):
		self.assertIn("border: 0;", self.template)
		self.assertIn("background: transparent;", self.template)

	def test_size_presets_pack_labels_across_the_page(self):
		small = ".size-small .qr-label-sheet { grid-template-columns: repeat(6, minmax(0, 1fr)); grid-template-rows: repeat(9, 31.222mm);"
		medium = ".size-medium .qr-label-sheet { grid-template-columns: repeat(5, minmax(0, 1fr)); grid-template-rows: repeat(8, 35.25mm);"
		large = ".size-large .qr-label-sheet { grid-template-columns: repeat(4, minmax(0, 1fr)); grid-template-rows: repeat(6, 47.333mm);"
		self.assertGreaterEqual(self.template.count(small), 2)
		self.assertGreaterEqual(self.template.count(medium), 2)
		self.assertGreaterEqual(self.template.count(large), 2)
		self.assertIn("const perSheet = { small: 54, medium: 40, large: 24 };", self.template)
		self.assertIn("qr-label-sheet", self.template)
		self.assertNotIn("--sheet-rows", self.template)
		self.assertIn("height: 289mm;", self.template)
		self.assertIn("grid-template-rows: minmax(0, 1fr) auto;", self.template)

	def test_print_grid_uses_minimal_spacing(self):
		self.assertIn("gap: 1mm;", self.template)

	def test_print_overrides_screen_minimum_height_for_every_size(self):
		self.assertIn(
			".size-small .qr-label, .size-medium .qr-label, .size-large .qr-label { min-height: 0; }",
			self.template,
		)

	def test_print_root_uses_explicit_a4_printable_width(self):
		self.assertIn("width: 202mm !important;", self.template)
		self.assertIn("width: 202mm;", self.template)

	def test_print_button_uses_isolated_document(self):
		self.assertIn('onclick="printQRLabels()"', self.template)
		self.assertIn('function printQRLabels()', self.template)
		self.assertIn('window.open("", "_blank")', self.template)
		self.assertIn('class="standalone-sheet-grid', self.template)
		self.assertIn('@page { size: A4 portrait; margin: 4mm; }', self.template)


if __name__ == "__main__":
	unittest.main()
