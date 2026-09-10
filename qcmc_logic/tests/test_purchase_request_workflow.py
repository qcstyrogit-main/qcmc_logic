import json
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock, patch

import frappe

from qcmc_logic.customs.purchase_request_workflow import (
    APPROVAL_STATES, DECISIONS, apply_workflow, validate_decision,
)
from qcmc_logic.patches.add_purchase_request_rejection import extend_workflow


class TestPurchaseRequestWorkflow(TestCase):
    def setUp(self):
        self.workflow = next(w for w in json.loads(
            (Path(__file__).parents[1] / 'fixtures/workflow.json').read_text()
        ) if w['name'] == 'Purchase Request')
        for target, value in (
            ('frappe.flags', frappe._dict()),
            ('frappe.session', frappe._dict(user='creator')),
        ):
            p = patch(target, value)
            p.start()
            self.addCleanup(p.stop)
        p = patch('frappe.throw', side_effect=frappe.ValidationError)
        p.start()
        self.addCleanup(p.stop)

    def test_actions_exist_only_at_approval_states_and_preserve_targets(self):
        decisions = [r for r in self.workflow['transitions'] if r['action'] in DECISIONS]
        self.assertEqual({r['state'] for r in decisions}, APPROVAL_STATES)
        self.assertEqual(len(decisions), 14)
        for row in decisions:
            self.assertEqual(row['next_state'], DECISIONS[row['action']])
        self.assertEqual(extend_workflow(self.workflow), self.workflow)
        self.assertFalse(any(r['state'] == 'Rejected' for r in self.workflow['transitions']))

    def doc(self, old_state, state, owner='creator'):
        old = frappe._dict(workflow_state=old_state, owner=owner)
        doc = frappe._dict(name='PR-1', material_request_type='Purchase', workflow_state=state)
        doc.get_doc_before_save = lambda: old
        return doc

    def test_direct_state_changes_cannot_bypass_reason(self):
        for target in DECISIONS.values():
            with self.assertRaises(frappe.ValidationError):
                validate_decision(self.doc('Pending QC PM Approval', target))
            frappe.flags.qcmc_purchase_decision = ('PR-1', 'Pending QC PM Approval', target)
            validate_decision(self.doc('Pending QC PM Approval', target))
            frappe.flags.qcmc_purchase_decision = None

    def test_rejected_cannot_be_edited_or_reopened(self):
        for target in ('Rejected', 'Draft'):
            with self.assertRaises(frappe.ValidationError):
                validate_decision(self.doc('Rejected', target))

    def test_only_creator_can_edit_or_resubmit_draft(self):
        validate_decision(self.doc('Draft', 'Pending PPIC Supervisor'))
        with self.assertRaises(frappe.ValidationError):
            validate_decision(self.doc('Draft', 'Draft', owner='someone-else'))

    def test_reason_required_and_audited_as_escaped_text(self):
        current = Mock(name='PR-1', material_request_type='Purchase', workflow_state='Pending QC PM Approval')
        current.name = 'PR-1'
        data = dict(doctype='Material Request', name='PR-1')
        with patch('frappe.get_doc', return_value=current), patch(
            'frappe.model.workflow.apply_workflow'
        ) as standard:
            for reason in (None, '', '  '):
                data['_qcmc_workflow_reason'] = reason
                with self.assertRaises(frappe.ValidationError):
                    apply_workflow(data, 'Reject')
            standard.assert_not_called()
            data['_qcmc_workflow_reason'] = '<script>bad</script>'
            result = apply_workflow(data, 'Reject')
            self.assertIn('&lt;script&gt;', result.add_comment.call_args.kwargs['text'])
            self.assertIsNone(frappe.flags.qcmc_purchase_decision)

    def test_normal_approval_delegates_unchanged(self):
        data = dict(doctype='Material Request', name='PR-1')
        with patch('frappe.model.workflow.apply_workflow') as standard:
            apply_workflow(data, 'Approve')
            standard.assert_called_once_with(data, 'Approve')
