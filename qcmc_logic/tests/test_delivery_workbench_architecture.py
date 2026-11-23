"""Regression checks for Query Report / workbench separation."""

import ast
import json
import unittest
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = APP_ROOT / "qcmc_logic"
WORKBENCHES = (
	"sales_order_delivery_scheduling_workbench",
	"delivery_schedule_workbench",
	"delivery_note_printing_workbench",
)
OPERATIONAL_WORKBENCHES = (
	"delivery_schedule_workbench",
	"delivery_note_printing_workbench",
)
SERVICES = (
	"sales_order_scheduling_service.py",
	"delivery_confirmation_service.py",
	"delivery_printing_service.py",
)
REPORTS = (
	("Sales Order Delivery Scheduling", "sales_order_delivery_scheduling/sales_order_delivery_scheduling.py"),
	("Delivery Schedule Confirmation", "delivery_schedule_confirmation/delivery_schedule_confirmation.py"),
	("Delivery Note Printing", "delivery_note_printing/delivery_note_printing.py"),
)


class TestDeliveryWorkbenchArchitecture(unittest.TestCase):
	def test_sales_finalized_delivery_note_has_no_reopen_workflow_transition(self):
		workflows = json.loads((APP_ROOT / "qcmc_logic" / "fixtures" / "workflow.json").read_text())
		delivery_note = next(row for row in workflows if row.get("doctype") == "Workflow" and row.get("name") == "Delivery Note")
		self.assertFalse(any(row.get("action") == "Reopen for Stock Confirmation" for row in delivery_note["transitions"]))

	def test_only_two_workbenches_are_exposed_to_operational_roles(self):
		page_root = APP_ROOT / "qcmc_logic" / "qcmc_logics" / "page"
		for page_name in OPERATIONAL_WORKBENCHES:
			page = json.loads((page_root / page_name / f"{page_name}.json").read_text())
			roles = {row["role"] for row in page.get("roles", [])}
			self.assertTrue(roles & {"Sales Coordinator", "Stock Confirm User", "Invoicing Clerk"}, page_name)
		legacy = json.loads((page_root / "sales_order_delivery_scheduling_workbench" /
			"sales_order_delivery_scheduling_workbench.json").read_text())
		self.assertEqual(legacy["title"], "Sales Order Delivery Scheduling Workbench")
		self.assertEqual({row["role"] for row in legacy["roles"]}, {"System Manager"})
		patch = (PACKAGE_ROOT / "patches" / "streamline_delivery_note_v2_workflow.py").read_text()
		self.assertIn("frappe.clear_cache(user=user)", patch)

	def test_draft_release_uses_schedule_link_without_operational_version_flag(self):
		workflows = json.loads((APP_ROOT / "qcmc_logic" / "fixtures" / "workflow.json").read_text())
		delivery_note = next(row for row in workflows if row.get("doctype") == "Workflow" and row.get("name") == "Delivery Note")
		release = next(row for row in delivery_note["transitions"]
			if row.get("state") == "Draft" and row.get("allowed") == "Invoicing Clerk")
		self.assertEqual(release["next_state"], "To Deliver and Bill")
		self.assertIn("doc.custom_dr_number", release["condition"])
		self.assertNotIn("custom_delivery_schedule_v2_enabled", release["condition"])
		self.assertIn("custom_so_delivery_schedule", release["condition"])
		self.assertTrue(any(row.get("state") == "Draft" and row.get("next_state") == "For Stock Confirmation"
			for row in delivery_note["transitions"]))
		self.assertTrue(any(row.get("state") == "For Stock Confirmation" and row.get("next_state") == "For DR Printing"
			for row in delivery_note["transitions"]))
		submit = next(row for row in delivery_note["transitions"]
			if row.get("state") == "To Deliver and Bill" and row.get("next_state") == "Completed")
		self.assertEqual(submit["allowed"], "Stock Confirm User")
		self.assertEqual(submit["action"], "Tag To Active")


	def test_workbench_python_and_service_modules_do_not_import_report_controllers(self):
		paths = [
			PACKAGE_ROOT / "qcmc_logics" / "page" / page / f"{page}.py"
			for page in WORKBENCHES
		]
		paths.extend(PACKAGE_ROOT / "api" / service for service in SERVICES)
		for path in paths:
			tree = ast.parse(path.read_text())
			for node in ast.walk(tree):
				if isinstance(node, ast.ImportFrom):
					self.assertFalse(
						(node.module or "").startswith("qcmc_logic.qcmc_logics.report."),
						f"{path} imports a Query Report controller",
					)
				if isinstance(node, ast.Import):
					self.assertFalse(
						any(alias.name.startswith("qcmc_logic.qcmc_logics.report.") for alias in node.names),
						f"{path} imports a Query Report controller",
					)

	def test_workbench_frontends_call_page_apis_and_not_query_report_methods(self):
		for page in WORKBENCHES:
			js = PACKAGE_ROOT / "qcmc_logics" / "page" / page / f"{page}.js"
			source = js.read_text()
			self.assertNotIn("frappe.query_reports", source, str(js))
			self.assertNotIn("qcmc_logic.qcmc_logics.report.", source, str(js))




	def test_deprecated_reports_are_disabled_in_definitions_and_fixtures(self):
		fixture_rows = json.loads((PACKAGE_ROOT / "fixtures" / "report.json").read_text())
		by_name = {row.get("name"): row for row in fixture_rows}
		for name, relative_path in REPORTS:
			with self.subTest(report=name):
				self.assertEqual(by_name[name].get("disabled"), 1)
				definition = json.loads((PACKAGE_ROOT / "qcmc_logics" / "report" / relative_path.replace(".py", ".json")).read_text())
				self.assertEqual(definition.get("disabled"), 1)

	def test_report_modules_are_deprecated_execute_only_compatibility_wrappers(self):
		for name, relative_path in REPORTS:
			with self.subTest(report=name):
				tree = ast.parse((PACKAGE_ROOT / "qcmc_logics" / "report" / relative_path).read_text())
				defined = [node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
				self.assertEqual(defined, [])
				imports = [node for node in tree.body if isinstance(node, ast.ImportFrom)]
				self.assertEqual(len(imports), 1)
				self.assertTrue(imports[0].module.startswith("qcmc_logic.api."))


if __name__ == "__main__":
	unittest.main()
