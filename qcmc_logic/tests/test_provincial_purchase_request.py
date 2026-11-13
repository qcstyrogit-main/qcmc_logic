import json
from copy import deepcopy
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock, patch

import frappe

from qcmc_logic.customs.provincial_purchase_request import (
    CREATOR, PROVINCIAL, ROLE, LOGISTICS, provincial_destination, restrict_provincial_permission,
)
from qcmc_logic.customs.purchase_request_evaluation import ASSET, NETWORK, validate_evaluation
from qcmc_logic.patches.add_provincial_purchase_request_routes import update_workflow


class TestProvincialPurchaseRequest(TestCase):
    def setUp(self):
        self.workflow = next(row for row in json.loads(
            (Path(__file__).parents[1] / 'fixtures/workflow.json').read_text()
        ) if row['name'] == 'Purchase Request')
        self.roles = [ROLE]
        for target, value in (
            ('frappe.session', frappe._dict(user='creator@example.com')),
            ('frappe.get_roles', lambda *a: self.roles),
            ('frappe.throw', Mock(side_effect=frappe.ValidationError)),
        ):
            p = patch(target, value);p.start();self.addCleanup(p.stop)

    def document(self, request_type='MIS', state='Draft', provincial=1):
        return frappe._dict(owner='creator@example.com', material_request_type='Purchase',
                            workflow_state=state, custom_request_type=request_type, docstatus=0,
                            custom_pr_original_creator='creator@example.com',
                            custom_pr_provincial_creator=provincial, items=[])

    def change(self, old, **values):
        doc = deepcopy(old);doc.update(values)
        doc.get_doc_before_save = lambda: old
        doc.set = lambda key, value: doc.update({key: value})
        return doc

    def test_creation_captures_authenticated_user_and_overwrites_spoofed_origin(self):
        for roles in ([ROLE], ['Stock User']):
            self.roles = roles
            doc = self.change(self.document(), custom_pr_original_creator='forged', custom_pr_provincial_creator=1)
            doc.get_doc_before_save = lambda: None
            validate_evaluation(doc)
            self.assertEqual(doc.get(CREATOR), 'creator@example.com')
            self.assertEqual(doc.get(PROVINCIAL), int(ROLE in roles))

    def test_provenance_and_owner_cannot_be_changed(self):
        for values in ({CREATOR: 'other'}, {PROVINCIAL: 0}, {'owner': 'other'}):
            with self.assertRaises(frappe.ValidationError):
                validate_evaluation(self.change(self.document(), **values))

    def test_draft_routes_are_exclusive_even_with_all_requester_roles(self):
        for request_type, expected in [('MIS', NETWORK), ('Office Supplies & Equipment', ASSET), ('Motorpool', LOGISTICS)]:
            doc = self.document(request_type)
            matches = [row for row in self.workflow['transitions'] if row['state'] == 'Draft'
                       and eval(row['condition'], {'__builtins__': {}}, {
                           'doc': doc, 'frappe': frappe._dict(session=frappe._dict(user=doc.owner))})]
            self.assertEqual([(r['allowed'], r['next_state']) for r in matches], [(ROLE, expected)])

    def test_nonprovincial_and_legacy_drafts_keep_existing_routes(self):
        for provincial in (0, None):
            doc = self.document(provincial=provincial)
            matches = [row for row in self.workflow['transitions'] if row['state'] == 'Draft'
                       and eval(row['condition'], {'__builtins__': {}}, {
                           'doc': doc, 'frappe': frappe._dict(session=frappe._dict(user=doc.owner))})]
            self.assertFalse(any(r['allowed'] == ROLE for r in matches))
            self.assertTrue(any(r['allowed'] == 'Network Admin' for r in matches))

    def test_direct_routes_stamp_evaluation_and_motorpool_has_no_evaluation(self):
        for request_type, target in [('MIS', NETWORK), ('Office Supplies & Equipment', ASSET), ('Motorpool', LOGISTICS)]:
            doc = self.change(self.document(request_type), workflow_state=target)
            validate_evaluation(doc)
            self.assertEqual(doc.get('custom_pr_evaluation_required'), None if target == LOGISTICS else target)

    def test_alternative_routes_and_direct_submission_are_blocked(self):
        for request_type in ('MIS', 'Office Supplies & Equipment', 'Motorpool'):
            old = self.document(request_type)
            for target in ('To Receive', 'Submitted', 'Pending MIS Supervisor Approval', 'Pending QC PM Approval'):
                with self.assertRaises(frappe.ValidationError):
                    validate_evaluation(self.change(old, workflow_state=target))
            with self.assertRaises(frappe.ValidationError):
                validate_evaluation(self.change(old, docstatus=1))

    def test_draft_type_edits_allowed_but_not_during_submission(self):
        old = self.document()
        validate_evaluation(self.change(old, custom_request_type='Motorpool'))
        with self.assertRaises(frappe.ValidationError):
            validate_evaluation(self.change(old, custom_request_type='Motorpool', workflow_state=LOGISTICS))

    def test_only_creator_with_current_role_can_submit(self):
        old = self.document()
        with patch('frappe.session', frappe._dict(user='other@example.com')):
            with self.assertRaises(frappe.ValidationError):
                validate_evaluation(self.change(old, workflow_state=NETWORK))
        self.roles = ['Stock User']
        with self.assertRaises(frappe.ValidationError):
            validate_evaluation(self.change(old, workflow_state=NETWORK))

    def test_later_routing_does_not_use_approver_provincial_membership(self):
        old = self.document(state=NETWORK)
        old.custom_pr_evaluation_required = NETWORK
        self.roles = ['Network Admin']
        with patch('qcmc_logic.customs.purchase_request_evaluation.now_datetime', return_value='2026-11-13 10:00:00'):
            doc = self.change(old, workflow_state='To Receive')
            validate_evaluation(doc)
            self.assertEqual(doc.custom_pr_evaluated_by, 'creator@example.com')

    def test_motorpool_requires_logistics_role_and_stable_type(self):
        old = self.document('Motorpool', LOGISTICS)
        for values in ({'docstatus': 1}, {'custom_request_type': 'Stockroom'}, {'workflow_state': NETWORK}, {'workflow_state': 'To Receive'}):
            with self.assertRaises(frappe.ValidationError):
                validate_evaluation(self.change(old, **values))
        self.roles = ['Logistics Manager']
        validate_evaluation(self.change(old, workflow_state='To Receive'))
        validate_evaluation(self.change(old, workflow_state='Cancelled Before Submission'))

    def test_role_grant_does_not_expand_nonpurchase_or_postdraft_write_access(self):
        with patch('frappe.get_meta', return_value=frappe._dict(permissions=[])):
            doc = self.document();doc.material_request_type='Material Transfer'
            self.assertFalse(restrict_provincial_permission(doc, 'create', 'creator@example.com'))
            doc = self.document();doc.name='PR-1';doc.workflow_state=NETWORK
            with patch('frappe.db', frappe._dict(get_value=Mock(return_value='Draft'))):
                self.assertIsNone(restrict_provincial_permission(doc, 'write', 'creator@example.com'))
            with patch('frappe.db', frappe._dict(get_value=Mock(return_value=NETWORK))):
                self.assertFalse(restrict_provincial_permission(doc, 'write', 'creator@example.com'))

    def test_other_types_and_patch_idempotence(self):
        self.assertIsNone(provincial_destination(self.document('Stockroom')))
        self.assertEqual(update_workflow(self.workflow), self.workflow)

    def test_new_provincial_requests_cannot_be_inserted_submitted(self):
        doc = self.change(self.document(), workflow_state='Submitted', docstatus=1)
        doc.get_doc_before_save = lambda: None
        with self.assertRaises(frappe.ValidationError):
            validate_evaluation(doc)

    def test_nonpurchase_type_change_cannot_skip_creator_based_routing(self):
        old = self.document();old.material_request_type = 'Material Transfer'
        doc = self.change(old, material_request_type='Purchase', workflow_state='To Receive')
        with self.assertRaises(frappe.ValidationError):
            validate_evaluation(doc)
        # A saved type change remains Draft; its next action follows the snapshot.
        doc = self.change(old, material_request_type='Purchase')
        validate_evaluation(doc)
        self.assertEqual(provincial_destination(doc), NETWORK)

    def test_partner_of_legacy_request_created_by_provincial_user_stays_draft(self):
        from types import SimpleNamespace
        from qcmc_logic.api.convertpr import convert_pr_to_partner

        item = Mock();item.name = 'ROW-1'
        source = SimpleNamespace(name='OLD-PR', company='Company A', workflow_state='Submitted',
                                 status='Draft', items=[item], db_set=Mock(), check_permission=Mock())
        source.get = lambda key, default=None: getattr(source, key, default)
        partner = Mock();partner.flags = frappe._dict()
        partner.get.side_effect = lambda key: {
            'material_request_type': 'Purchase', PROVINCIAL: 1, 'custom_request_type': 'MIS',
        }.get(key)
        with patch('frappe.get_doc', return_value=source), patch('frappe.copy_doc', side_effect=[partner, Mock()]), \
                patch('frappe.logger', return_value=Mock()), patch('frappe.msgprint'), \
                patch('frappe.db', frappe._dict(commit=Mock())), \
                patch('qcmc_logic.api.convertpr.nowdate', return_value='2026-11-13'):
            convert_pr_to_partner('OLD-PR', 'Company B', 'Warehouse B', ['ROW-1'])
        self.assertEqual(partner.workflow_state, 'Draft')
        self.assertEqual(partner.docstatus, 0)
        partner.db_set.assert_not_called()
