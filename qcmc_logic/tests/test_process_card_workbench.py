import json
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock, patch

from frappe import _dict

from qcmc_logic.api import process_card_workbench as api


ROOT = Path(__file__).parents[1]


def job(name="JC-1", **values):
	row = dict(
		name=name, status="Open", docstatus=0, work_order="WO-1", operation="Cut",
		operation_id="WO-OP-1", production_item="ITEM-1", for_quantity=100,
		total_completed_qty=40, actual_start_date="2026-11-10 06:00:00",
		actual_end_date=None,
	)
	row.update(values)
	return _dict(row)


class TestProcessCardWorkbenchAPI(TestCase):
	@patch("qcmc_logic.api.process_card_workbench.get_process_card_context")
	@patch("qcmc_logic.api.process_card_workbench.frappe")
	def test_batch_context_filters_accessible_cards_by_site_shift_and_building_workstations(self, frappe, context):
		layout = {"buildings": [{"id": "building-1", "label": "Building 1", "interior": {"elements": [
			{"kind": "machine", "workstation": "WS-1"},
		]}}]}
		frappe.db.exists.return_value = True
		frappe.get_doc.return_value = _dict(check_permission=Mock())
		frappe.get_list.side_effect = [
			[_dict(name="Day")],
			[_dict(layout_json=json.dumps(layout))],
			[_dict(name="PC-1", workstation="WS-1"), _dict(name="PC-3", workstation="WS-1"), _dict(name="PC-2", workstation="WS-2")],
		]
		frappe.db.get_value.return_value = "Product One"
		context.side_effect = [{
			"process_card": {"name": "PC-1", "status": "Draft", "workstation_name": "Machine 1", "building": "Building 1", "shift_start": "2026-11-10 06:00:00", "shift_end": "2026-11-10 18:00:00"},
			"can_record_output": True,
			"job_cards": [{"name": "JC-1", "docstatus": 0, "status": "Open", "work_order": "WO-1", "operation": "Cut", "production_item": "ITEM-1", "can_record_output": True}],
			"production_output": {"per_job": [{"job_card": "JC-1", "uom": "Nos", "soph": 10, "color_count": 2, "entries": []}]},
		}, {
			"process_card": {"name": "PC-3", "status": "Draft", "workstation_name": "Machine 1", "building": "Building 1", "shift_start": "2026-11-10 06:00:00", "shift_end": "2026-11-10 18:00:00"},
			"can_record_output": True,
			"job_cards": [{"name": "JC-3", "docstatus": 0, "status": "Open", "work_order": "WO-3", "operation": "Pack", "production_item": "ITEM-3", "can_record_output": True}],
			"production_output": {"per_job": [{"job_card": "JC-3", "uom": "Nos", "soph": 5, "color_count": 1, "entries": []}]},
		}]
		result = api.get_batch_output_context("Guyong", "2026-11-10", "Day", "building-1")
		self.assertEqual([row["process_card"] for row in result["rows"]], ["PC-1", "PC-3"])
		self.assertEqual(result["rows"][0]["soph"], 10)
		self.assertEqual(result["rows"][0]["color_count"], 2)
		self.assertEqual(result["rows"][1]["job_card"], "JC-3")
		filters = frappe.get_list.call_args_list[2].kwargs["filters"]
		self.assertEqual(filters["site"], "Guyong")
		self.assertEqual(filters["shift_date"], "2026-11-10")
		self.assertEqual(filters["shift_type"], "Day")
		self.assertEqual(context.call_args_list[0].args, ("PC-1",))
		self.assertEqual(context.call_args_list[1].args, ("PC-3",))

	@patch("qcmc_logic.api.process_card_workbench.get_process_card_context")
	@patch("qcmc_logic.api.process_card_workbench.frappe")
	def test_batch_context_includes_job_card_write_permission_for_row_actions(self, frappe, context):
		frappe.db.exists.return_value = True
		frappe.get_doc.return_value = _dict(check_permission=Mock())
		frappe.get_list.side_effect = [[_dict(name="Day")], [], [_dict(name="PC-1", workstation="WS-1")]]
		context.return_value = {
			"process_card": {"name": "PC-1", "status": "Draft", "workstation_name": "Machine 1", "building": "Building 1", "shift_start": "2026-11-10 06:00:00", "shift_end": "2026-11-10 18:00:00"},
			"can_record_output": True,
			"job_cards": [{"name": "JC-1", "docstatus": 0, "status": "Open", "work_order": "WO-1", "operation": "Cut", "production_item": "ITEM-1", "can_record_output": True}],
			"production_output": {"per_job": [{"job_card": "JC-1", "entries": []}]},
		}
		frappe.has_permission.return_value = True
		row = api.get_batch_output_context("Guyong", "2026-11-10", "Day")["rows"][0]
		self.assertTrue(row["can_record_output"])
		self.assertTrue(row["can_correct_output"])
		frappe.has_permission.assert_called_with("Job Card", "write", doc=frappe.get_doc.return_value)

	@patch("qcmc_logic.api.process_card_workbench.frappe")
	def test_creation_search_supplies_work_order_permissions_for_operation_fields(self, frappe):
		def get_list(doctype, **kwargs):
			if doctype == "Job Card":
				return [
					job(),
					job("JC-HIDDEN", work_order="WO-HIDDEN"),
					job("JC-MISSING-OP", operation_id=None),
				]
			if doctype == "Work Order":
				return [_dict(name="WO-1")]
			if doctype == "Work Order Operation":
				# v16 otherwise strips parent/operation and returns only the name.
				if kwargs.get("parent_doctype") != "Work Order":
					return [_dict(name="WO-OP-1")]
				self.assertEqual(kwargs["filters"]["parent"], ["in", ["WO-1"]])
				self.assertEqual(kwargs["filters"]["parenttype"], "Work Order")
				return [_dict(name="WO-OP-1", parent="WO-1", operation="Cut")]
			self.fail(f"Unexpected query: {doctype}")
		frappe.get_list.side_effect = get_list
		rows = api._eligible_creation_job_cards("Company A", "WS-1")
		self.assertEqual([row.name for row in rows], ["JC-1"])

	@patch("qcmc_logic.api.process_card_workbench._building_for_process_card", return_value="Building A")
	@patch("qcmc_logic.api.process_card_workbench._job_output_standards", return_value={"soph": None, "color_count": None, "output_item": "ITEM-1"})
	@patch("qcmc_logic.api.process_card_workbench._job_card")
	@patch("qcmc_logic.api.process_card_workbench._process_card")
	@patch("qcmc_logic.api.process_card_workbench.frappe")
	def test_context_loads_multiple_job_cards_with_native_quantities(self, frappe, process_card, job_card, standards, building):
		process_card.return_value = _dict(
			name="PC-1", status="For Approval", company="Company A", site="Guyong", workstation="WS-1",
			shift_date="2026-11-10", shift_type="Day", shift_start="2026-11-10 06:00:00",
			shift_end="2026-11-10 14:00:00", jobs=[_dict(job_card="JC-1"), _dict(job_card="JC-2")],
		)
		frappe.get_doc.return_value = _dict(
			name="WS-1", workstation_name="Machine 1", workstation_type="Press", status="Available",
			description="Press", plant_floor="FLOOR-1",
		)
		frappe.db.get_value.return_value = None
		job_card.side_effect = [(job("JC-1"), _dict(name="WO-1")), (job("JC-2", work_order="WO-2"), _dict(name="WO-2"))]
		frappe.has_permission.side_effect = [False, False, False, True]
		frappe.get_roles.return_value = ["Manufacturing User"]
		result = api.get_process_card_context("PC-1")
		self.assertEqual([row["name"] for row in result["job_cards"]], ["JC-1", "JC-2"])
		self.assertEqual(result["job_cards"][0]["for_quantity"], 100)
		self.assertEqual(result["job_cards"][0]["total_completed_qty"], 40)
		self.assertEqual(result["job_cards"][0]["actual_start_date"], "2026-11-10 06:00:00")
		self.assertNotIn("pending_qty", result["job_cards"][0])
		self.assertEqual(result["process_card"]["building"], "Building A")
		self.assertFalse(result["can_write"])
		self.assertNotIn("Approved", result["allowed_transitions"])

	@patch("qcmc_logic.api.process_card_workbench._process_card")
	@patch("qcmc_logic.api.process_card_workbench.frappe")
	def test_search_limits_to_company_workstation_submitted_work_orders_and_skips_already_linked(self, frappe, process_card):
		process_card.return_value = _dict(company="Company A", workstation="WS-1", jobs=[_dict(job_card="JC-LINKED")])
		frappe.has_permission.return_value = True
		frappe.get_list.side_effect = [
			[_dict(name="JC-LINKED", work_order="WO-1"), _dict(name="JC-ELIGIBLE", work_order="WO-2", operation="Cut", operation_id="WO-OP-2"), _dict(name="JC-NO-WO", work_order="WO-3")],
			[_dict(name="WO-2")],
			[],
		]
		rows = api.search_eligible_job_cards("PC-1", "ITEM")
		self.assertEqual([row.name for row in rows], ["JC-ELIGIBLE"])
		filters = frappe.get_list.call_args_list[0].kwargs["filters"]
		self.assertEqual(filters["company"], "Company A")
		self.assertEqual(filters["workstation"], "WS-1")
		self.assertEqual(filters["docstatus"], ["!=", 2])
		self.assertTrue(frappe.get_list.call_args_list[0].kwargs["or_filters"])

	@patch("qcmc_logic.api.process_card_workbench._", side_effect=lambda value: value)
	@patch("qcmc_logic.api.process_card_workbench._lock_process_card")
	@patch("qcmc_logic.api.process_card_workbench.frappe")
	def test_duplicate_association_is_rejected_before_mutation(self, frappe, lock, translate):
		card = _dict(jobs=[_dict(job_card="JC-1")], append=lambda *args: self.fail("Must not append duplicate"))
		lock.return_value = card
		frappe.throw.side_effect = ValueError("duplicate")
		with self.assertRaises(ValueError):
			api.add_job_cards("PC-1", '["JC-1"]')

	@patch("qcmc_logic.api.process_card_workbench.get_process_card_context", return_value={"refreshed": True})
	@patch("qcmc_logic.api.process_card_workbench._job_card")
	@patch("qcmc_logic.api.process_card_workbench._lock_process_card")
	def test_multiple_job_cards_are_associated_once_under_locked_parent(self, lock, job_card, get_context):
		rows = []
		card = _dict(name="PC-1", company="Company A", workstation="WS-1", jobs=rows, append=lambda field, values: rows.append(_dict(**values)), save=lambda: None)
		lock.return_value = card
		job_card.side_effect = [(job("JC-1"), _dict(name="WO-1")), (job("JC-2", work_order="WO-2"), _dict(name="WO-2"))]
		self.assertEqual(api.add_job_cards("PC-1", '["JC-1", "JC-2"]'), {"refreshed": True})
		self.assertEqual([row.job_card for row in rows], ["JC-1", "JC-2"])
		self.assertEqual(rows[0].work_order, "WO-1")
		self.assertNotIn("for_quantity", rows[0])
		get_context.assert_called_once_with("PC-1")

	@patch("qcmc_logic.api.process_card_workbench._new_card_context")
	@patch("qcmc_logic.api.process_card_workbench._job_card")
	@patch("qcmc_logic.api.process_card_workbench.frappe")
	def test_workbench_creation_saves_process_card_with_selected_job_cards(self, frappe, job_card, creation_context):
		allocated = []
		card = _dict(append=lambda field, values: allocated.append(_dict(**values)), insert=Mock(), name="PC-NEW", status="Draft")
		frappe.new_doc.return_value = card
		frappe.parse_json.side_effect = json.loads
		frappe.get_list.return_value = [_dict(name="Day")]
		job_card.side_effect = [(job("JC-1"), _dict(name="WO-1")), (job("JC-2", work_order="WO-2"), _dict(name="WO-2"))]
		creation_context.return_value = (_dict(name="Guyong", company="Company A"), _dict(name="WS-1"))

		result = api.create_process_card(
			"Company A", "Guyong", "WS-1", "2026-11-10", "Day",
			"2026-11-10 06:00:00", "2026-11-10 18:00:00", '["JC-1", "JC-2"]', "Shift notes",
		)

		self.assertEqual(result, {"name": "PC-NEW", "status": "Draft"})
		self.assertEqual([row.job_card for row in allocated], ["JC-1", "JC-2"])
		self.assertEqual([row.work_order for row in allocated], ["WO-1", "WO-2"])
		self.assertEqual(card.shift_type, "Day")
		self.assertEqual(card.remarks, "Shift notes")
		card.insert.assert_called_once_with()

	@patch("qcmc_logic.api.process_card_workbench._new_card_context")
	@patch("qcmc_logic.api.process_card_workbench.frappe")
	def test_workbench_creation_requires_selected_job_cards(self, frappe, creation_context):
		frappe.throw.side_effect = ValueError("select Job Cards")
		with self.assertRaises(ValueError):
			api.create_process_card("Company A", "Guyong", "WS-1", "2026-11-10", "Day", "06:00", "18:00", "[]")
		creation_context.assert_not_called()

	@patch("qcmc_logic.api.process_card_workbench._", side_effect=lambda value: value)
	@patch("qcmc_logic.api.process_card_workbench.frappe")
	def test_cancelled_job_card_is_rejected(self, frappe, translate):
		frappe.db.exists.return_value = True
		frappe.get_doc.return_value = _dict(
			name="JC-CANCELLED", docstatus=2, status="Cancelled", check_permission=lambda permission: None,
		)
		frappe.throw.side_effect = ValueError("cancelled")
		with self.assertRaises(ValueError):
			api._job_card("JC-CANCELLED", "Company A", "WS-1")

	@patch("qcmc_logic.api.process_card_workbench._", side_effect=lambda value: value)
	@patch("qcmc_logic.api.process_card_workbench.frappe")
	def test_job_card_permission_is_required_before_association(self, frappe, translate):
		def deny(permission):
			raise PermissionError(permission)
		frappe.db.exists.return_value = True
		frappe.get_doc.return_value = _dict(name="JC-1", check_permission=deny)
		with self.assertRaises(PermissionError):
			api._job_card("JC-1", "Company A", "WS-1")

	@patch("qcmc_logic.api.process_card_workbench._", side_effect=lambda value: value)
	@patch("qcmc_logic.api.process_card_workbench.frappe")
	def test_job_card_must_match_company_workstation_and_submitted_work_order(self, frappe, translate):
		frappe.db.exists.return_value = True
		frappe.get_doc.side_effect = [
			_dict(name="JC-OTHER-WS", work_order="WO-1", company="Company A", workstation="WS-2", status="Open", docstatus=0, check_permission=lambda permission: None),
		]
		frappe.throw.side_effect = ValueError("invalid workstation")
		with self.assertRaises(ValueError):
			api._job_card("JC-OTHER-WS", "Company A", "WS-1")
		frappe.get_doc.side_effect = [
			job("JC-UNSUBMITTED", company="Company A", workstation="WS-1", check_permission=lambda permission: None),
			_dict(name="WO-DRAFT", company="Company A", docstatus=0, check_permission=lambda permission: None),
		]
		with self.assertRaises(ValueError):
			api._job_card("JC-UNSUBMITTED", "Company A", "WS-1")

	@patch("qcmc_logic.api.process_card_workbench._", side_effect=lambda value: value)
	@patch("qcmc_logic.api.process_card_workbench.frappe")
	def test_closed_work_order_remains_readable_for_shift_review_but_not_assignment(self, frappe, translate):
		job_card = job(status="Completed", check_permission=Mock())
		work_order = _dict(
			name="WO-1",
			company="Company A",
			docstatus=1,
			status="Completed",
			check_permission=Mock(),
		)
		frappe.db.exists.return_value = True
		frappe.get_doc.side_effect = [job_card, job_card, work_order, job_card, work_order]
		frappe.throw.side_effect = lambda message, *args, **kwargs: (_ for _ in ()).throw(ValueError(message))

		with self.assertRaisesRegex(ValueError, "already completed"):
			api._job_card("JC-1", "Company A", "WS-1")

		job_card.status = "Open"
		with self.assertRaisesRegex(ValueError, "submitted Work Order"):
			api._job_card("JC-1", "Company A", "WS-1")

		job_card.status = "Completed"
		loaded_job, loaded_work_order = api._job_card(
			"JC-1", "Company A", "WS-1", allow_historical=True,
		)
		self.assertIs(loaded_job, job_card)
		self.assertIs(loaded_work_order, work_order)

	@patch("qcmc_logic.api.process_card_workbench._editable_process_card")
	@patch("qcmc_logic.api.process_card_workbench.frappe")
	def test_association_lock_precedes_document_reload_and_validation(self, frappe, editable):
		editable.return_value = _dict(name="PC-1")
		self.assertEqual(api._lock_process_card("PC-1").name, "PC-1")
		frappe.db.sql.assert_called_once_with("select name from `tabProcess Card` where name=%s for update", "PC-1")
		editable.assert_called_once_with("PC-1")

	@patch("qcmc_logic.api.process_card_workbench._", side_effect=lambda value: value)
	@patch("qcmc_logic.api.process_card_workbench.frappe")
	def test_direct_process_card_load_checks_document_permission(self, frappe, translate):
		card = _dict(company="Company A", check_permission=lambda permission: (_ for _ in ()).throw(PermissionError(permission)))
		frappe.db.exists.return_value = True
		frappe.get_doc.return_value = card
		with self.assertRaises(PermissionError):
			api._process_card("PC-SECRET", "write")

	@patch("qcmc_logic.api.process_card_workbench._", side_effect=lambda value: value)
	@patch("qcmc_logic.api.process_card_workbench._process_card")
	@patch("qcmc_logic.api.process_card_workbench.frappe")
	def test_invalid_status_transition_is_rejected(self, frappe, process_card, translate):
		process_card.return_value = _dict(name="PC-1", status="Approved", save=lambda: self.fail("Must not save"))
		frappe.throw.side_effect = ValueError("invalid status")
		with self.assertRaises(ValueError):
			api.transition_status("PC-1", "In Progress")

	def test_page_role_route_hooks_and_native_quantity_schema_are_present(self):
		page = json.loads((ROOT / "qcmc_logics/page/process_card_workbench/process_card_workbench.json").read_text())
		self.assertEqual(page["page_name"], "process-card-workbench")
		self.assertIn({"role": "Manufacturing User"}, page["roles"])
		self.assertIn('"Process Card": "public/js/process_card.js"', (ROOT / "hooks.py").read_text())
		source = (ROOT / "qcmc_logics/page/process_card_workbench/process_card_workbench.js").read_text()
		self.assertIn('frappe.set_route("Form", "Job Card", id)', source)
		self.assertIn('"for_quantity"', (ROOT / "api/process_card_workbench.py").read_text())
		self.assertIn('"total_completed_qty"', (ROOT / "api/process_card_workbench.py").read_text())
		self.assertIn('"actual_start_date"', (ROOT / "api/process_card_workbench.py").read_text())
		self.assertIn('"actual_end_date"', (ROOT / "api/process_card_workbench.py").read_text())

