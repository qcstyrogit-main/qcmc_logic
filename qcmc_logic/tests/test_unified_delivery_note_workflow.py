from unittest import TestCase
from unittest.mock import MagicMock, patch
import frappe
from qcmc_logic.patches import unify_delivery_note_workflow as migration
from qcmc_logic.api import delivery_printing_service as printing


class TestUnifiedDeliveryWorkflow(TestCase):
    def test_transition_update_preserves_provincial_and_cancellation(self):
        workflow = MagicMock()
        workflow.states = [frappe._dict(state=state) for state in
            ("Draft", "For Stock Confirmation", "For DR Printing", "To Deliver and Bill", "Completed", "Cancelled")]
        workflow.transitions = [frappe._dict(state=a, action=b, next_state=c, allowed=d,
            condition="existing") for a, b, c, d in sorted(migration.KNOWN)]
        migration._update_workflow(workflow)
        states = workflow.set.call_args_list[0].args[1]
        transitions = workflow.set.call_args_list[1].args[1]
        self.assertFalse(any(row.state in migration.RETIRED for row in states))
        self.assertEqual({migration.signature(row) for row in transitions}, migration.REQUIRED | {migration.RELEASE})
        release = next(row for row in transitions if migration.signature(row) == migration.RELEASE)
        self.assertEqual(release.condition, migration.RELEASE_CONDITION)

    def test_manual_standalone_draft_and_unlinked_so(self):
        doc = frappe._dict(docstatus=0, workflow_state="Draft", is_return=0,
            company="QC", items=[frappe._dict(warehouse="WH")])
        with patch.object(printing, "_is_head_office_note", return_value=True):
            self.assertTrue(printing._is_manual_printing_draft(doc))
            doc.items[0].against_sales_order = "SO-1"
            self.assertFalse(printing._is_manual_printing_draft(doc))
            doc.items[0].against_sales_order = None
            doc.custom_sales_order = "SO-1"
            self.assertFalse(printing._is_manual_printing_draft(doc))

    def test_provincial_notes_excluded_from_printing_queue(self):
        doc = frappe._dict(docstatus=0, workflow_state="Draft", is_return=0,
            company="QC", items=[frappe._dict(warehouse="PROVINCE")])
        with patch.object(printing, "_is_head_office_note", return_value=False):
            self.assertFalse(printing._is_printable_queue_document(doc))
