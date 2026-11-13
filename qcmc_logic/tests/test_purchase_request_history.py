import json
from unittest import TestCase
from unittest.mock import patch

import frappe

from qcmc_logic.customs.purchase_request_history import (
    FIELD, approved_users, validate_history, set_history_preference,
)


class TestPurchaseRequestHistory(TestCase):
    def setUp(self):
        for target, value in (
            ('frappe.session', frappe._dict(user='approver@example.com')),
            ('frappe.throw', lambda message: (_ for _ in ()).throw(frappe.ValidationError(message))),
        ):
            p = patch(target, value);p.start();self.addCleanup(p.stop)

    def document(self, source, target, users=None, request_type='Purchase'):
        old = frappe._dict(workflow_state=source, material_request_type=request_type,
                           custom_pr_previous_approvers=json.dumps(users) if users is not None else None)
        doc = frappe._dict(old);doc.workflow_state=target
        doc.get_doc_before_save = lambda: old
        doc.set = lambda key, value: doc.update({key: value})
        return doc

    def test_manager_ppic_and_evaluator_approvals_record_actor(self):
        for source, target in (
            ('Pending QC PM Approval', 'Pending Network Admin Evaluation'),
            ('Pending PPIC Supervisor', 'Pending QC PM Approval'),
            ('Pending Network Admin Evaluation', 'To Receive'),
            ('Pending Asset Management Evaluation', 'To Receive'),
        ):
            doc = self.document(source, target)
            validate_history(doc)
            self.assertEqual(approved_users(doc.get(FIELD)), ['approver@example.com'])

    def test_saves_submission_receipt_and_cancellation_do_not_grant_history(self):
        for source, target in (
            ('Pending QC PM Approval', 'Pending QC PM Approval'),
            ('Draft', 'Pending QC PM Approval'), ('To Receive', 'Received'),
            ('Received', 'Submitted'), ('Pending QC PM Approval', 'Cancelled Before Submission'),
        ):
            doc = self.document(source, target)
            validate_history(doc)
            self.assertEqual(approved_users(doc.get(FIELD)), [])
        doc = self.document('Pending QC PM Approval', 'To Receive', request_type='Material Transfer')
        validate_history(doc)
        self.assertEqual(approved_users(doc.get(FIELD)), [])

    def test_membership_is_deduplicated_and_prior_approvers_are_retained(self):
        doc = self.document('Pending MC PM Approval', 'To Receive', ['other@example.com', 'approver@example.com'])
        validate_history(doc)
        self.assertEqual(approved_users(doc.get(FIELD)), ['other@example.com', 'approver@example.com'])

    def test_history_cannot_be_supplied_or_modified(self):
        doc = self.document('Pending MC PM Approval', 'To Receive')
        doc[FIELD] = '["forged@example.com"]'
        with self.assertRaises(frappe.ValidationError):validate_history(doc)
        doc.get_doc_before_save = lambda: None
        with self.assertRaises(frappe.ValidationError):validate_history(doc)
        doc = self.document('Received', 'Received', ['approver@example.com'])
        doc[FIELD] = None
        with self.assertRaises(frappe.ValidationError):validate_history(doc)

    def test_preference_can_only_set_current_users_boolean(self):
        with patch('frappe.defaults.set_user_default') as setter:
            self.assertEqual(set_history_preference('1'), 1)
            self.assertEqual(setter.call_args.kwargs['user'], 'approver@example.com')
            with self.assertRaises(frappe.ValidationError):set_history_preference('anything')
