import json
from datetime import datetime
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock, patch

import frappe

from qcmc_logic.customs.purchase_request_evaluation import (
    ASSET, NETWORK, EVIDENCE, MANAGERS, required_evaluation, validate_evaluation,
)
from qcmc_logic.patches.add_purchase_request_evaluations import update_workflow


class TestPurchaseRequestEvaluations(TestCase):
    def setUp(self):
        self.workflow = next(row for row in json.loads(
            (Path(__file__).parents[1] / 'fixtures/workflow.json').read_text()
        ) if row['name'] == 'Purchase Request')
        for target, value in (
            ('frappe.throw', lambda message: (_ for _ in ()).throw(frappe.ValidationError(message))),
            ('frappe.session', frappe._dict(user='evaluator@example.com')),
            ('frappe.get_roles', lambda: ['Network Admin', 'Asset Management User']),
            ('qcmc_logic.customs.purchase_request_evaluation.now_datetime', lambda: datetime(2026, 11, 12, 10)),
        ):
            mock = patch(target, value)
            mock.start()
            self.addCleanup(mock.stop)

    def document(self, state, request_type='MIS', **values):
        data = frappe._dict(material_request_type='Purchase', custom_request_type=request_type,
                            workflow_state=state, company='QC Styropackaging Corporation',
                            items=[frappe._dict(item_code='ITEM-1', qty=1, uom='Nos')])
        data.update(values)
        return data

    def change(self, old, state=None, **values):
        from copy import deepcopy
        doc = deepcopy(old)
        doc.update(values)
        if state:
            doc.workflow_state = state
        doc.get_doc_before_save = lambda: old
        doc.set = lambda key, value: doc.update({key: value})
        return doc

    def test_manager_routing_matrix_and_original_conditions(self):
        for state in MANAGERS | {'Pending Approval'}:
            for request_type in ('MIS', 'Office Supplies & Equipment', 'Stockroom', None):
                for company in ('QC Styropackaging Corporation', 'Other Company'):
                    doc = self.document(state, request_type, company=company)
                    matches = [row for row in self.workflow['transitions']
                               if row['state'] == state and row['action'] == 'Approve'
                               and eval(row['condition'], {'__builtins__': {}}, {'doc': doc})]
                    allowed = not (
                        (state == 'Pending QC PM Approval' and company != 'QC Styropackaging Corporation')
                        or (state == 'Pending MC PM Approval' and company == 'QC Styropackaging Corporation')
                    )
                    with self.subTest(state=state, request_type=request_type, company=company):
                        self.assertEqual(len(matches), int(allowed))
                        if allowed:
                            self.assertEqual(matches[0]['next_state'], required_evaluation(doc) or 'To Receive')

    def test_patch_is_idempotent(self):
        self.assertEqual(update_workflow(self.workflow), self.workflow)

    def test_other_routes_unchanged(self):
        rows = self.workflow['transitions']
        self.assertTrue(any(r['state'] == 'Pending MIS Supervisor Approval' and r['action'] == 'Approve'
                            and r['next_state'] == 'To Receive' and r['condition'] == 'doc.material_request_type == "Purchase"'
                            for r in rows))
        self.assertTrue(any(r['state'] == 'Draft' and r['allowed'] == 'Stock User'
                            and r['next_state'] == 'Submitted'
                            and eval(r['condition'], {'__builtins__': {}}, {'doc': self.document('Draft', material_request_type='Material Transfer')})
                            for r in rows))

    def test_manager_cannot_skip_evaluation(self):
        for request_type, target in [('MIS', NETWORK), ('Office Supplies & Equipment', ASSET)]:
            old = self.document('Pending QC PM Approval', request_type)
            for state in ('To Receive', 'Received', 'Submitted', ASSET if target == NETWORK else NETWORK):
                with self.subTest(request_type=request_type, state=state), self.assertRaises(frappe.ValidationError):
                    validate_evaluation(self.change(old, state))
            doc = self.change(old, target)
            validate_evaluation(doc)
            self.assertEqual(doc.custom_pr_evaluation_required, target)
            self.assertIsNone(doc.custom_pr_evaluated_by)

    def test_type_changes_cannot_evade_evaluation(self):
        old = self.document('Pending QC PM Approval')
        for values in ({'custom_request_type': 'Stockroom'}, {'material_request_type': 'Material Transfer'}):
            with self.assertRaises(frappe.ValidationError):
                validate_evaluation(self.change(old, 'To Receive', **values))
        old = self.document('Pending QC PM Approval', 'Stockroom')
        with self.assertRaises(frappe.ValidationError):
            validate_evaluation(self.change(old, 'To Receive', custom_request_type='MIS'))

    def test_evaluator_role_and_server_audit(self):
        for state, request_type, role in [(NETWORK, 'MIS', 'Network Admin'),
                                          (ASSET, 'Office Supplies & Equipment', 'Asset Management User')]:
            old = self.document(state, request_type, custom_pr_evaluation_required=state)
            with patch('frappe.get_roles', return_value=['Purchase User']):
                with self.assertRaises(frappe.ValidationError):
                    validate_evaluation(self.change(old, 'To Receive'))
            with patch('frappe.get_roles', return_value=[role]):
                doc = self.change(old, 'To Receive')
                validate_evaluation(doc)
                self.assertEqual(doc.custom_pr_evaluated_by, 'evaluator@example.com')
                self.assertIsNotNone(doc.custom_pr_evaluated_on)

    def test_evidence_cannot_be_forged_or_cleared(self):
        old = self.document(NETWORK, custom_pr_evaluation_required=NETWORK)
        for key in EVIDENCE:
            with self.assertRaises(frappe.ValidationError):
                validate_evaluation(self.change(old, **{key: 'forged'}))
        new = self.change(self.document('Draft'), custom_pr_evaluated_by='forged')
        new.get_doc_before_save = lambda: None
        with self.assertRaises(frappe.ValidationError):
            validate_evaluation(new)

    def test_evaluation_cannot_submit_directly(self):
        old = self.document(NETWORK, custom_pr_evaluation_required=NETWORK)
        with self.assertRaises(frappe.ValidationError):
            validate_evaluation(self.change(old, 'Submitted'))
        for state in (NETWORK, 'Pending QC PM Approval'):
            old = self.document(state, custom_pr_evaluation_required=NETWORK if state == NETWORK else None)
            with self.assertRaises(frappe.ValidationError):
                validate_evaluation(self.change(old, docstatus=1))

    def test_approved_details_locked_but_fulfilment_updates_allowed(self):
        old = self.document('To Receive', custom_pr_evaluation_required=NETWORK,
                            custom_pr_evaluated_by='evaluator@example.com', custom_pr_evaluated_on='2026-11-12 10:00:00')
        changed = self.change(old)
        changed['items'][0].qty = 2
        with self.assertRaises(frappe.ValidationError):
            validate_evaluation(changed)
        changed = self.change(old, 'Received')
        changed['items'][0].ordered_qty = 1
        validate_evaluation(changed)

    def test_legacy_and_excluded_source_states_not_retroactively_gated(self):
        for state in ('To Receive', 'Received', 'Submitted', 'Pending MIS Supervisor Approval'):
            old = self.document(state)
            validate_evaluation(self.change(old, 'To Receive' if state.startswith('Pending') else state))
        old = self.document('Pending Approval', 'Office Supplies & Equipment')
        doc = self.change(old, 'To Receive')
        validate_evaluation(doc)
        self.assertFalse(doc.get(EVIDENCE[0]))

    def test_cancellation_remains_available(self):
        old = self.document(NETWORK, custom_pr_evaluation_required=NETWORK)
        validate_evaluation(self.change(old, 'Cancelled Before Submission'))

    def test_cannot_edit_items_in_the_same_approval_request(self):
        old = self.document(NETWORK, custom_pr_evaluation_required=NETWORK)
        changed = self.change(old, 'To Receive')
        changed['items'][0].qty = 2
        with self.assertRaises(frappe.ValidationError):
            validate_evaluation(changed)

    def test_partner_conversion_cannot_skip_pending_manager_evaluation(self):
        from qcmc_logic.api.convertpr import convert_pr_to_partner
        source = self.document('Pending QC PM Approval')
        source.check_permission = Mock()
        with patch('frappe.get_doc', return_value=source), patch('frappe.logger', return_value=Mock()), \
                patch('frappe.copy_doc') as copy:
            with self.assertRaises(frappe.ValidationError):
                convert_pr_to_partner('PR-1', 'Other Company', 'Other Warehouse', ['ROW-1'])
            copy.assert_not_called()

    def test_partner_of_evaluated_request_starts_in_draft_without_evidence(self):
        from qcmc_logic.api.convertpr import convert_pr_to_partner
        from types import SimpleNamespace
        source = self.document('Submitted', custom_pr_evaluation_required=NETWORK,
                               custom_pr_evaluated_by='evaluator@example.com')
        source = SimpleNamespace(**source)
        source.status = 'Pending'
        source.get = lambda key, default=None: getattr(source, key, default)
        source.name = 'PR-1'
        source.check_permission = Mock()
        source.db_set = Mock()
        source.items[0].name = 'ROW-1'
        source.items[0].as_dict = lambda: {}
        source.items[0].db_set = Mock()
        partner = Mock()
        partner.flags = frappe._dict()
        item = Mock()
        with patch('frappe.get_doc', return_value=source), patch('frappe.logger', return_value=Mock()), \
                patch('frappe.copy_doc', side_effect=[partner, item]), \
                patch('frappe.msgprint'), patch('frappe.db', frappe._dict(commit=Mock())), \
                patch('qcmc_logic.api.convertpr.nowdate', return_value='2026-11-12'):
            convert_pr_to_partner('PR-1', 'Other Company', 'Other Warehouse', ['ROW-1'])
        self.assertEqual(partner.workflow_state, 'Draft')
        self.assertEqual(partner.docstatus, 0)
        partner.db_set.assert_not_called()
        for key in EVIDENCE:
            partner.set.assert_any_call(key, None)
