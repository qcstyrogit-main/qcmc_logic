import json
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from frappe import _dict

from qcmc_logic.qcmc_logics.doctype.process_card.process_card import ProcessCard


ROOT = Path(__file__).parents[1] / "qcmc_logics" / "doctype"


def make_card(**kwargs):
	card = object.__new__(ProcessCard)
	values = dict(
		name="PC-TEST", workstation="WS-1", company="Company A", site=None,
		shift_start="2026-11-09 06:00:00", shift_end="2026-11-09 14:00:00",
		status="Draft", jobs=[], is_new=lambda: False,
		get_doc_before_save=lambda: None, get=lambda key, default=None: getattr(card, key, default),
	)
	values.update(kwargs)
	card.__dict__.update(values)
	return card


class TestProcessCardSchemas(TestCase):
	def test_only_expected_doc_types_are_created_and_child_has_no_quantity_fields(self):
		main = json.loads((ROOT / "process_card" / "process_card.json").read_text())
		child = json.loads((ROOT / "process_card_job" / "process_card_job.json").read_text())
		self.assertEqual(main["name"], "Process Card")
		self.assertEqual(child["name"], "Process Card Job")
		fields = {row["fieldname"] for row in child["fields"]}
		self.assertEqual(fields, {"job_card", "work_order", "operation", "production_item"})


class TestProcessCardShiftCloseout(TestCase):
	def test_unconfirmed_output_prevents_closeout(self):
		card = make_card()
		with patch("qcmc_logic.qcmc_logics.doctype.process_card.process_card._", side_effect=lambda value: value), patch("qcmc_logic.qcmc_logics.doctype.process_card.process_card.frappe") as frappe:
			frappe.db.exists.return_value = "TL-1"
			frappe.throw.side_effect = ValueError("Confirm all declared production output")
			with self.assertRaisesRegex(ValueError, "Confirm all declared production output"):
				card._validate_shift_closeout()

	def test_open_employee_interval_prevents_closeout(self):
		card = make_card()
		with patch("qcmc_logic.qcmc_logics.doctype.process_card.process_card._", side_effect=lambda value: value), patch("qcmc_logic.qcmc_logics.doctype.process_card.process_card.frappe") as frappe:
			frappe.db.exists.side_effect = [None, "TL-2"]
			frappe.throw.side_effect = ValueError("Close all employee participation intervals")
			with self.assertRaisesRegex(ValueError, "Close all employee participation intervals"):
				card._validate_shift_closeout()

	def test_manufacturing_manager_and_system_manager_can_approve(self):
		card = make_card(status="Approved", get_doc_before_save=lambda: _dict(status="For Approval"))
		with patch("qcmc_logic.qcmc_logics.doctype.process_card.process_card.frappe") as frappe:
			frappe.db.exists.return_value = None
			card._apply_status_policy()
			frappe.only_for.assert_called_once_with(("System Manager", "Manufacturing Manager"))


class TestProcessCardShiftValidation(TestCase):
	def test_overnight_shift_is_valid_when_end_is_next_day(self):
		card = make_card(shift_start="2026-11-09 22:00:00", shift_end="2026-11-10 06:00:00")
		card._validate_shift_interval()

	def test_non_positive_interval_rejected(self):
		card = make_card(shift_start="2026-11-09 22:00:00", shift_end="2026-11-09 06:00:00")
		with patch("qcmc_logic.qcmc_logics.doctype.process_card.process_card._", side_effect=lambda value: value), patch("qcmc_logic.qcmc_logics.doctype.process_card.process_card.frappe") as frappe:
			frappe.throw.side_effect = ValueError("invalid")
			with self.assertRaises(ValueError):
				card._validate_shift_interval()

	@patch("qcmc_logic.qcmc_logics.doctype.process_card.process_card._", side_effect=lambda value: value)
	@patch("qcmc_logic.qcmc_logics.doctype.process_card.process_card.frappe")
	def test_workstation_company_mismatch_is_rejected(self, frappe, translate):
		card = make_card(site=None)
		frappe.db.exists.side_effect = lambda doctype, name: doctype == "Workstation"
		frappe.get_doc.return_value = _dict(name="WS-1", disabled=0, plant_floor="FLOOR-1", check_permission=lambda permission: None)
		frappe.get_list.return_value = ["Company A"]
		frappe.db.get_value.return_value = "Company B"
		frappe.throw.side_effect = ValueError("company mismatch")
		with self.assertRaises(ValueError):
			card._validate_company_and_workstation()

	@patch("qcmc_logic.qcmc_logics.doctype.process_card.process_card._", side_effect=lambda value: value)
	@patch("qcmc_logic.qcmc_logics.doctype.process_card.process_card.frappe")
	def test_production_site_must_include_workstation_floor(self, frappe, translate):
		card = make_card(site="Guyong")
		frappe.db.exists.side_effect = lambda doctype, name: doctype in {"Workstation", "Production Site"}
		frappe.get_doc.side_effect = [
			_dict(name="WS-1", disabled=0, plant_floor="FLOOR-1", check_permission=lambda permission: None),
			_dict(name="Guyong", company="Company A", plant_floors=[_dict(plant_floor="OTHER-FLOOR")], check_permission=lambda permission: None),
		]
		frappe.get_list.return_value = ["Company A"]
		frappe.db.get_value.return_value = "Company A"
		frappe.throw.side_effect = ValueError("site mismatch")
		with self.assertRaises(ValueError):
			card._validate_company_and_workstation()

	@patch("qcmc_logic.qcmc_logics.doctype.process_card.process_card.frappe")
	def test_multiple_distinct_job_cards_are_accepted_and_fields_derived(self, frappe):
		card = make_card(jobs=[_dict(job_card="JC-1"), _dict(job_card="JC-2")])
		jobs = {
			"JC-1": _dict(name="JC-1", work_order="WO-1", operation="Cut", operation_id="WO-OP-1", production_item="ITEM-1", workstation="WS-1", company="Company A", docstatus=0, status="Open", check_permission=lambda permission: None),
			"JC-2": _dict(name="JC-2", work_order="WO-2", operation="Pack", operation_id="WO-OP-2", production_item="ITEM-2", workstation="WS-1", company="Company A", docstatus=0, status="Open", check_permission=lambda permission: None),
		}
		work_orders = {name: _dict(name=name, company="Company A", docstatus=1, check_permission=lambda permission: None) for name in ("WO-1", "WO-2")}
		frappe.db.exists.return_value = True
		frappe.get_doc.side_effect = lambda doctype, name: jobs[name] if doctype == "Job Card" else work_orders[name]
		card._validate_jobs()
		self.assertEqual(card.jobs[0].work_order, "WO-1")
		self.assertEqual(card.jobs[1].operation, "Pack")

	@patch("qcmc_logic.qcmc_logics.doctype.process_card.process_card.frappe")
	def test_same_job_card_can_be_explicitly_associated_with_later_shift_card(self, frappe):
		job_card = _dict(name="JC-1", work_order="WO-1", operation="Cut", operation_id="WO-OP-1", production_item="ITEM-1", workstation="WS-1", company="Company A", docstatus=0, status="Open", check_permission=lambda permission: None)
		work_order = _dict(name="WO-1", company="Company A", docstatus=1, check_permission=lambda permission: None)
		frappe.db.exists.return_value = True
		frappe.get_doc.side_effect = lambda doctype, name: job_card if doctype == "Job Card" else work_order
		first = make_card(shift_start="2026-11-09 06:00:00", shift_end="2026-11-09 14:00:00", jobs=[_dict(job_card="JC-1")])
		later = make_card(name="PC-LATER", shift_start="2026-11-09 14:00:00", shift_end="2026-11-09 22:00:00", jobs=[_dict(job_card="JC-1")])
		first._validate_jobs()
		later._validate_jobs()
		self.assertEqual(first.jobs[0].job_card, later.jobs[0].job_card)

	@patch("qcmc_logic.qcmc_logics.doctype.process_card.process_card.frappe")
	def test_existing_process_card_can_be_reviewed_after_work_order_completion(self, frappe):
		job_card = _dict(
			name="JC-1", work_order="WO-1", operation="Cut", operation_id="WO-OP-1",
			production_item="ITEM-1", workstation="WS-1", company="Company A",
			docstatus=0, status="Completed", check_permission=lambda permission: None,
		)
		work_order = _dict(
			name="WO-1", company="Company A", docstatus=1, status="Completed",
			check_permission=lambda permission: None,
		)
		frappe.db.exists.return_value = True
		frappe.get_doc.side_effect = lambda doctype, name: job_card if doctype == "Job Card" else work_order
		previous = _dict(jobs=[_dict(job_card="JC-1")])
		card = make_card(
			jobs=[_dict(job_card="JC-1")],
			get_doc_before_save=lambda: previous,
		)

		card._validate_jobs()

	@patch("qcmc_logic.qcmc_logics.doctype.process_card.process_card.frappe")
	@patch("qcmc_logic.qcmc_logics.doctype.process_card.process_card._", side_effect=lambda value: value)
	def test_duplicate_job_card_rejected(self, translate, frappe):
		card = make_card(jobs=[_dict(job_card="JC-1"), _dict(job_card="JC-1")])
		job_card = _dict(name="JC-1", work_order="WO-1", operation="Cut", operation_id="WO-OP-1", production_item="ITEM-1", workstation="WS-1", company="Company A", docstatus=0, status="Open", check_permission=lambda permission: None)
		work_order = _dict(name="WO-1", company="Company A", docstatus=1, check_permission=lambda permission: None)
		frappe.db.exists.return_value = True
		frappe.get_doc.side_effect = lambda doctype, name: job_card if doctype == "Job Card" else work_order
		frappe.throw.side_effect = ValueError("duplicate")
		with self.assertRaises(ValueError):
			card._validate_jobs()

	def test_approved_document_is_immutable(self):
		previous = _dict(status="Approved", company="Company A", site=None, workstation="WS-1", shift_date="2026-11-09", shift_type="Shift 1", shift_start="2026-11-09 06:00:00", shift_end="2026-11-09 14:00:00", remarks=None, jobs=[])
		card = make_card(status="Approved", get_doc_before_save=lambda: previous, shift_date="2026-11-09", shift_type="Shift 1", remarks="changed")
		with patch("qcmc_logic.qcmc_logics.doctype.process_card.process_card._", side_effect=lambda value: value), patch("qcmc_logic.qcmc_logics.doctype.process_card.process_card.frappe") as frappe:
			frappe.throw.side_effect = ValueError("immutable")
			with self.assertRaises(ValueError):
				card._apply_status_policy()
