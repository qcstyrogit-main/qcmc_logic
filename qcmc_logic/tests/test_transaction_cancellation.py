"""Focused unit regressions. Run against the installed Frappe version."""
from unittest import TestCase
from unittest.mock import MagicMock, patch

import frappe
from qcmc_logic.customs import transaction_cancellation as service


class TestTransactionCancellation(TestCase):
    def draft(self):
        doc = MagicMock()
        doc.doctype = "Delivery Note"
        doc.name = "DN-TEST"
        doc.docstatus = 0
        doc.modified = "2026-11-26 10:00:00"
        doc.meta.is_submittable = 1
        doc.meta.istable = 0
        doc.meta.issingle = 0
        doc.is_new.return_value = False
        doc.has_permission.return_value = True
        return doc

    def test_setting_disabled_rejects_discard(self):
        with patch.object(service, "enabled", return_value=False):
            with self.assertRaises(frappe.ValidationError):
                service._require_enabled(self.draft())

    def test_permission_required(self):
        doc = self.draft()
        doc.has_permission.side_effect = lambda p: p != "cancel"
        with patch.object(service, "enabled", return_value=True):
            with self.assertRaises(frappe.PermissionError):
                service._require_enabled(doc)

    def test_reject_submitted(self):
        doc = self.draft()
        doc.docstatus = 1
        with patch.object(service, "enabled", return_value=True):
            with self.assertRaises(frappe.ValidationError):
                service._require_enabled(doc)

    def test_reason_validation(self):
        for value in (None, "", "   ", "x" * 2001):
            with self.subTest(value=str(value)[:10]):
                with self.assertRaises(frappe.ValidationError):
                    service._reason(value)
        self.assertEqual(service._reason("  Not pursued "), "Not pursued")

    def test_stale_document_rejected(self):
        with self.assertRaises(frappe.TimestampMismatchError):
            service._check_modified(self.draft(), "old")

    def test_direct_native_discard_requires_authorized_context(self):
        with patch.object(service, "_require_enabled"), patch.object(frappe, "flags", frappe._dict()):
            with self.assertRaises(frappe.PermissionError):
                service.before_discard(self.draft())

    def test_no_workflow_endpoint_cannot_bypass_workflow(self):
        with (
            patch.object(frappe, "get_doc", return_value=self.draft()),
            patch.object(service, "_require_enabled"),
            patch.object(service.wf, "get_workflow_name", return_value="Delivery Note"),
            patch.object(service, "_discard") as execute,
        ):
            with self.assertRaises(frappe.PermissionError):
                service.discard("Delivery Note", "DN-TEST", "Not pursued", self.draft().modified)
            execute.assert_not_called()

    def test_transition_classification(self):
        doc = self.draft()
        workflow = frappe._dict(states=[frappe._dict(state="Cancelled", doc_status="2")])
        transition = frappe._dict(next_state="Cancelled")
        self.assertTrue(service._is_draft_cancel(doc, workflow, transition))
        doc.docstatus = 1
        self.assertFalse(service._is_draft_cancel(doc, workflow, transition))

    def workflow_fixture(self, transitions=None, state="Draft"):
        doc = self.draft()
        doc.get.side_effect = lambda field: state if field == "workflow_state" else None
        workflow = frappe._dict(workflow_state_field="workflow_state",
            states=[frappe._dict(state="Draft", doc_status="0", allow_edit="Sales User"),
                    frappe._dict(state="For Approval", doc_status="0", allow_edit="Sales Manager"),
                    frappe._dict(state="Cancelled Before Submission", doc_status="0", allow_edit="Sales User"),
                    frappe._dict(state="Cancelled", doc_status="2", allow_edit="Sales Manager")],
            transitions=transitions or [])
        return doc, workflow

    def test_automatic_cancel_without_explicit_transition(self):
        doc, workflow = self.workflow_fixture()
        with (patch.object(service, "enabled", return_value=True),
              patch.object(frappe, "get_roles", return_value=["Sales User"])):
            routes = service._draft_routes(doc, workflow, [])
            self.assertEqual(len(routes), 1)
            self.assertEqual(routes[0].action, "Cancel")
            self.assertEqual(routes[0].next_state, "Cancelled")
            self.assertTrue(routes[0]._qcmc_automatic_cancel)

    def test_automatic_cancel_at_pending_state(self):
        doc, workflow = self.workflow_fixture(state="For Approval")
        with (patch.object(service, "enabled", return_value=True),
              patch.object(frappe, "get_roles", return_value=["Sales Manager"])):
            self.assertEqual(service._draft_routes(doc, workflow, [])[0].allowed, "Sales Manager")

    def test_automatic_cancel_requires_current_edit_role(self):
        doc, workflow = self.workflow_fixture(state="For Approval")
        with (patch.object(service, "enabled", return_value=True),
              patch.object(frappe, "get_roles", return_value=["Sales User"])):
            self.assertEqual(service._draft_routes(doc, workflow, []), [])

    def test_explicit_restricted_route_is_not_bypassed(self):
        route = frappe._dict(state="Draft", action="Cancel", next_state="Cancelled",
            allowed="Sales Manager", condition="doc.company == 'QC'", allow_self_approval=1)
        doc, workflow = self.workflow_fixture([route])
        with (patch.object(service, "enabled", return_value=True),
              patch.object(frappe, "get_roles", return_value=["Sales User"])):
            self.assertEqual(service._draft_routes(doc, workflow, []), [])

    def test_legacy_cancel_is_promoted_to_true_docstatus_two(self):
        route = frappe._dict(state="Draft", action="Cancel", next_state="Cancelled Before Submission",
            allowed="Sales User", condition=None, allow_self_approval=1)
        doc, workflow = self.workflow_fixture([route])
        with (patch.object(service, "enabled", return_value=True),
              patch.object(service.wf, "has_approval_access", return_value=True)):
            result = service._draft_routes(doc, workflow, [route])
            self.assertEqual(result[0].next_state, "Cancelled")
            self.assertEqual(route.next_state, "Cancelled Before Submission")

    def test_disabled_setting_and_terminal_states_have_no_automatic_cancel(self):
        doc, workflow = self.workflow_fixture()
        with patch.object(service, "enabled", return_value=False):
            self.assertEqual(service._draft_routes(doc, workflow, []), [])
        doc, workflow = self.workflow_fixture(state="Cancelled Before Submission")
        with patch.object(service, "enabled", return_value=True):
            self.assertEqual(service._draft_routes(doc, workflow, []), [])

    def test_non_submittable_has_no_automatic_cancel(self):
        doc, workflow = self.workflow_fixture()
        doc.meta.is_submittable = 0
        with patch.object(service, "enabled", return_value=True):
            self.assertEqual(service._draft_routes(doc, workflow, []), [])

    def test_statusless_stock_entry_discard_all_purposes(self):
        from erpnext.stock.doctype.stock_entry.stock_entry import StockEntry
        from qcmc_logic.overrides.stock_entry import CustomStockEntry

        for purpose in ("Material Transfer for Manufacture", "Material Issue",
                        "Material Receipt", "Material Transfer", "Manufacture",
                        "Material Consumption for Manufacture", "Repack"):
            with self.subTest(purpose=purpose):
                doc = CustomStockEntry({"doctype": "Stock Entry", "purpose": purpose})
                if doc.meta.has_field("status"):
                    self.skipTest("This site has a custom Stock Entry status field.")
                with patch.object(StockEntry, "on_discard") as inherited:
                    doc.on_discard()
                    inherited.assert_not_called()
