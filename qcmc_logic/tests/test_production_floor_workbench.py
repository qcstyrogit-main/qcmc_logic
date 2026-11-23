import copy
import json
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from frappe import _dict

from qcmc_logic.api.production_floor_workbench import _site_for_floor, get_machine_context, get_floor_context, list_sites, save_layout
from qcmc_logic.qcmc_logics.doctype.production_floor_layout.production_floor_layout import validate_layout


ROOT = Path(__file__).parents[1] / "qcmc_logics"


def layout():
	return {
		"width": 1200, "height": 800,
		"buildings": [{
			"id": "b1", "kind": "building", "label": "Building A",
			"x": 50, "y": 50, "w": 400, "h": 350, "color": "#d9e8ef",
			"interior": {"width": 1200, "height": 800, "elements": [{
				"id": "m1", "kind": "machine", "label": "Machine 1",
				"x": 100, "y": 100, "w": 160, "h": 100,
				"color": "#eed9aa", "workstation": "WS-1",
			}]},
		}],
	}


class TestFloorLayoutValidation(TestCase):
	@patch("qcmc_logic.qcmc_logics.doctype.production_floor_layout.production_floor_layout.frappe")
	def test_building_and_machine_geometry_validates_against_existing_workstation(self, frappe):
		frappe.get_all.return_value = [_dict(name="WS-1", plant_floor="PLANT-A", disabled=0)]
		frappe.has_permission.return_value = True
		validate_layout(layout(), "PLANT-A")
		frappe.get_all.assert_called_once()

	@patch("qcmc_logic.qcmc_logics.doctype.production_floor_layout.production_floor_layout.frappe")
	def test_invalid_geometry_and_duplicate_workstation_rejected(self, frappe):
		frappe.throw.side_effect = ValueError("invalid")
		invalid = layout(); invalid["buildings"][0]["x"] = 1100
		with self.assertRaises(ValueError):
			validate_layout(invalid, "PLANT-A")
		duplicate = layout()
		second = copy.deepcopy(duplicate["buildings"][0]["interior"]["elements"][0])
		second["id"] = "m2"
		duplicate["buildings"][0]["interior"]["elements"].append(second)
		with self.assertRaises(ValueError):
			validate_layout(duplicate, "PLANT-A")

	@patch("qcmc_logic.qcmc_logics.doctype.production_floor_layout.production_floor_layout.frappe")
	def test_wrong_plant_workstation_rejected(self, frappe):
		frappe.get_all.return_value = [_dict(name="WS-1", plant_floor="OTHER", disabled=0)]
		frappe.throw.side_effect = ValueError("wrong plant")
		with self.assertRaises(ValueError):
			validate_layout(layout(), "PLANT-A")


class TestFloorLayoutAPI(TestCase):
	@patch("qcmc_logic.api.production_floor_workbench.frappe")
	@patch("qcmc_logic.api.production_floor_workbench._site")
	@patch("qcmc_logic.api.production_floor_workbench._company_names", return_value={"Company A"})
	def test_machine_context_filters_cards_by_workstation_date_and_optional_shift(self, companies, site, frappe):
		site.return_value = _dict(name="Guyong", company="Company A", plant_floors=["PLANT-A"])
		frappe.get_list.side_effect = [[_dict(name="WS-1", workstation_name="Machine 1", workstation_type="Press", status="Available", description="Press")], [_dict(name="PC-1", shift_date="2026-11-10", shift_type="Day", status="In Progress", docstatus=0)]]
		frappe.has_permission.return_value = True
		result = get_machine_context("Guyong", "WS-1", "2026-11-10", "Day")
		self.assertEqual(result["workstation"].name, "WS-1")
		self.assertEqual([row.name for row in result["process_cards"]], ["PC-1"])
		self.assertTrue(result["can_create"])
		self.assertEqual(frappe.get_list.call_args_list[1].kwargs["filters"], {"company": "Company A", "workstation": "WS-1", "shift_date": "2026-11-10", "shift_type": "Day"})

	@patch("qcmc_logic.api.production_floor_workbench.frappe")
	@patch("qcmc_logic.api.production_floor_workbench._site")
	@patch("qcmc_logic.api.production_floor_workbench._company_names", return_value={"Company A"})
	def test_machine_context_handles_missing_or_inaccessible_workstation_without_card_query(self, companies, site, frappe):
		site.return_value = _dict(name="Guyong", company="Company A", plant_floors=["PLANT-A"])
		frappe.get_list.return_value = []
		result = get_machine_context("Guyong", "WS-HIDDEN", "2026-11-10")
		self.assertTrue(result["unavailable"])
		self.assertEqual(result["process_cards"], [])
		frappe.get_list.assert_called_once()
		frappe.has_permission.assert_not_called()

	@patch("qcmc_logic.api.production_floor_workbench.frappe")
	@patch("qcmc_logic.api.production_floor_workbench._site")
	@patch("qcmc_logic.api.production_floor_workbench._company_names", return_value={"Company A"})
	def test_machine_context_create_permission_is_reported_and_date_always_filtered(self, companies, site, frappe):
		site.return_value = _dict(name="Guyong", company="Company A", plant_floors=["PLANT-A"])
		frappe.get_list.side_effect = [[_dict(name="WS-1")], []]
		frappe.has_permission.return_value = False
		result = get_machine_context("Guyong", "WS-1", "2026-11-10")
		self.assertFalse(result["can_create"])
		self.assertEqual(frappe.get_list.call_args_list[1].kwargs["filters"], {"company": "Company A", "workstation": "WS-1", "shift_date": "2026-11-10"})

	@patch("qcmc_logic.api.production_floor_workbench.frappe")
	@patch("qcmc_logic.api.production_floor_workbench._site")
	@patch("qcmc_logic.api.production_floor_workbench._company_names", return_value={"Company A"})
	def test_initial_floor_context_does_not_fetch_sitewide_process_cards(self, companies, site, frappe):
		site.return_value = _dict(name="Guyong", plant_floors=["PLANT-A"])
		frappe.get_list.return_value = [_dict(name="WS-1")]
		result = get_floor_context("Guyong")
		self.assertEqual(len(result["workstations"]), 1)
		self.assertEqual(frappe.get_list.call_count, 1)

	def test_supplied_floor_name_mapping(self):
		qc = "QC StyroPackaging Corporation"
		mc = "MultiPlast Corporation"
		self.assertEqual(_site_for_floor(_dict(name="EXTRUSION33", floor_name="EXTRUSION33", company=qc)), "Sta Clara")
		self.assertEqual(_site_for_floor(_dict(name="DRYER-ROOM", floor_name="DRYER-ROOM", company=qc)), "Guyong")
		self.assertEqual(_site_for_floor(_dict(name="FORMING-MC2", floor_name="FORMING-MC2", company=mc)), "MC 2")
		self.assertEqual(_site_for_floor(_dict(name="INJECTION99", floor_name="INJECTION99", company=mc)), "MC 2")
		self.assertEqual(_site_for_floor(_dict(name="SHRINKWRAP99", floor_name="SHRINKWRAP99", company=mc)), "MC 2")
		self.assertEqual(_site_for_floor(_dict(name="CUPS PRINTING", floor_name="CUPS PRINTING", company=mc)), "MC 1")

	@patch("qcmc_logic.api.production_floor_workbench._company_names", return_value={"Company A"})
	@patch("qcmc_logic.api.production_floor_workbench.frappe")
	def test_sidebar_contains_only_four_sites_in_order(self, frappe, companies):
		frappe.get_list.return_value = [_dict(name="Guyong")]
		rows = list_sites()
		self.assertEqual([row["name"] for row in rows], ["Guyong", "Sta Clara", "MC 1", "MC 2"])
		self.assertEqual([row["configured"] for row in rows], [True, False, False, False])

	@patch("qcmc_logic.api.production_floor_workbench._can_edit", return_value=False)
	@patch("qcmc_logic.api.production_floor_workbench._company_names", return_value={"Company A"})
	@patch("qcmc_logic.api.production_floor_workbench._site")
	@patch("qcmc_logic.api.production_floor_workbench.frappe")
	def test_manufacturing_viewer_cannot_save(self, frappe, site, companies, can_edit):
		site.return_value = _dict(name="Guyong", company="Company A", plant_floors=["PLANT-A"])
		frappe.PermissionError = PermissionError
		frappe.throw.side_effect = PermissionError("manager required")
		with self.assertRaises(PermissionError):
			save_layout("Guyong", layout(), 0)
		frappe.db.sql.assert_not_called()

	@patch("qcmc_logic.api.production_floor_workbench.validate_layout")
	@patch("qcmc_logic.api.production_floor_workbench._can_edit", return_value=True)
	@patch("qcmc_logic.api.production_floor_workbench._company_names", return_value={"Company A"})
	@patch("qcmc_logic.api.production_floor_workbench._site")
	@patch("qcmc_logic.api.production_floor_workbench.frappe")
	def test_stale_save_rejected_after_site_lock(self, frappe, site, companies, can_edit, validate):
		site.return_value = _dict(name="Guyong", company="Company A", plant_floors=["PLANT-A"])
		frappe.db.get_value.return_value = _dict(name="Guyong", layout_version=3)
		frappe.db.exists.return_value = True
		frappe.TimestampMismatchError = RuntimeError
		frappe.throw.side_effect = RuntimeError("stale")
		with self.assertRaises(RuntimeError):
			save_layout("Guyong", layout(), 2)
		self.assertEqual(frappe.db.sql.call_count, 2)
		frappe.new_doc.assert_not_called()

	def test_page_and_storage_schema_are_registered(self):
		page = json.loads((ROOT / "page" / "production_floor_workbench" / "production_floor_workbench.json").read_text())
		storage = json.loads((ROOT / "doctype" / "production_floor_layout" / "production_floor_layout.json").read_text())
		self.assertEqual(page["page_name"], "production-floor-workbench")
		self.assertEqual(storage["name"], "Production Floor Layout")
		self.assertTrue(next(f for f in storage["fields"] if f["fieldname"] == "production_site")["unique"])
