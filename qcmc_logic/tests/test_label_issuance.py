import json
from pathlib import Path
from unittest import TestCase


ROOT = Path(__file__).parents[1]


class TestLabelIssuancePage(TestCase):
	def test_page_is_owned_by_qcmc_app_with_manufacturing_roles(self):
		page = json.loads((ROOT / "qcmc_logics/page/label_issuance/label_issuance.json").read_text())
		self.assertEqual(page["page_name"], "label-issuance")
		# The owning module controls the source path used by Frappe. Setting this to
		# Manufacturing incorrectly makes Frappe search inside the ERPNext app.
		self.assertEqual(page["module"], "QCMC Logics")
		self.assertEqual({row["role"] for row in page["roles"]}, {"Manufacturing User", "Manufacturing Manager", "System Manager"})

	def test_business_field_mappings_are_explicit(self):
		script = (ROOT / "qcmc_logics/page/label_issuance/label_issuance.js").read_text()
		self.assertIn('make("company", "Company", "Link", "Company", true', script)
		self.assertIn('make("plant_floor", "Section", "Link", "Plant Floor", true)', script)
		self.assertIn('filters: {company: this.company.get_value() || ""}', script)
		self.assertIn('make("shift_type", "Shift", "Link", "Shift Type", false)', script)
		self.assertIn('__("PC No")', script)
		self.assertIn('__("JO No")', script)
