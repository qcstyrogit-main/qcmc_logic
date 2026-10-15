import unittest
from unittest.mock import patch
from email.message import EmailMessage

import frappe
from qcmc_logic.api import desk_notifications as api


class TestDeskNotifications(unittest.TestCase):
    def setUp(self):
        session = patch.object(frappe, 'session', frappe._dict(user='person@example.com'))
        session.start(); self.addCleanup(session.stop)

    def test_mime_email_alert_links_to_announcement(self):
        message = EmailMessage()
        message.set_content('Notification')
        message.add_alternative('<blockquote><a href="/desk?qcmc_announcement=WRONG">Other</a></blockquote><div class="more-info"><a href="https://erp.example/desk?qcmc_announcement=ANN-1">Open</a></div>', subtype='html')
        row = frappe.get_doc({'doctype': 'Notification Log', 'document_type': 'Email Queue', 'document_name': 'QUEUE-1'})
        with patch.object(frappe.db, 'get_value', return_value=frappe._dict(message=message.as_string())), patch.object(frappe.utils, 'get_url', return_value='https://erp.example'):
            self.assertEqual(api.announcement_target(row), 'ANN-1')

    def test_unrelated_email_links_do_not_become_announcement_notifications(self):
        row = frappe._dict(document_type='Email Queue', document_name='QUEUE-1')
        for html in ['<a href="/desk?qcmc_announcement=ANN-1">Link in body</a>', '<div class="more-info"><a href="https://other.example/desk?qcmc_announcement=ANN-1">Open</a></div>']:
            message = EmailMessage(); message.set_content(html, subtype='html')
            with patch.object(frappe.db, 'get_value', return_value=frappe._dict(message=message.as_string())), patch.object(frappe.utils, 'get_url', return_value='https://erp.example'):
                self.assertIsNone(api.announcement_target(row))

    def test_legacy_mentions_and_unrelated_alerts(self):
        self.assertEqual(api.announcement_target(frappe._dict(document_type='Announcements', document_name='ANN-1')), 'ANN-1')
        self.assertIsNone(api.announcement_target(frappe._dict(document_type='Quiz', document_name='Q-1')))
        self.assertEqual(api._target_from_url('/desk/announcements/ANN%201'), 'ANN 1')
        self.assertIsNone(api._target_from_url('/desk/email-queue/Q-1'))

    def test_own_unread_count_and_read_authorization(self):
        with patch.object(frappe.db, 'count', return_value=7) as count:
            self.assertEqual(api.get_unread_count(), 7)
        count.assert_called_once_with('Notification Log', {'for_user': 'person@example.com', 'read': 0})
        with patch.object(frappe, 'get_doc', return_value=frappe._dict(for_user='other@example.com')):
            with self.assertRaises(frappe.PermissionError): api.open_announcement_notification('N-1')

    def test_open_marks_read_only_after_active_check(self):
        row = frappe._dict(for_user='person@example.com', document_type='Announcements', document_name='ANN-1')
        with patch.object(frappe, 'get_doc', return_value=row), patch.object(api, '_active'), patch.object(frappe.db, 'set_value') as update:
            self.assertEqual(api.open_announcement_notification('N-1'), {'announcement': 'ANN-1'})
            update.assert_called_once()
        with patch.object(frappe, 'get_doc', return_value=row), patch.object(api, '_active', side_effect=frappe.PermissionError), patch.object(frappe.db, 'set_value') as update:
            with self.assertRaises(frappe.PermissionError): api.open_announcement_notification('N-1')
            update.assert_not_called()

    def test_unrelated_legacy_queue_keeps_native_read_on_click(self):
        row = frappe._dict(for_user='person@example.com', document_type='Email Queue', document_name='Q-1')
        with patch.object(frappe, 'get_doc', return_value=row), patch.object(api, 'announcement_target', return_value=None), patch.object(frappe.db, 'set_value') as update:
            self.assertEqual(api.open_announcement_notification('N-1'), {'announcement': None})
            update.assert_called_once_with('Notification Log', 'N-1', 'read', 1, update_modified=False)

    def test_dropdown_preserves_unrelated_links(self):
        rows = [frappe._dict(document_type='Announcements', document_name='ANN-1'), frappe._dict(document_type='Quiz', link='/desk/quiz/Q-1')]
        with patch.object(frappe, 'get_all', return_value=rows), patch.object(frappe.utils, 'add_user_info'):
            result = api.get_notification_logs()
        self.assertIn('qcmc_announcement=ANN-1', result['notification_logs'][0]['link'])
        self.assertEqual(result['notification_logs'][1]['link'], '/desk/quiz/Q-1')

    def test_administrator_dropdown_is_still_personal(self):
        with patch.object(frappe, 'session', frappe._dict(user='Administrator')), patch.object(frappe, 'get_all', return_value=[]) as query:
            api.get_notification_logs()
        self.assertEqual(query.call_args.kwargs['filters'], {'for_user': 'Administrator'})

    def test_notification_comment_prefers_verified_id_and_handles_legacy_matches(self):
        row = frappe._dict(link='/desk?qcmc_announcement=ANN-1&qcmc_comment=C-1')
        with patch.object(api, 'validated_comment', return_value='C-1'):
            self.assertEqual(api.notification_comment(row, 'ANN-1'), 'C-1')
        row = frappe._dict(email_content='<p>Hello Person</p>', from_user='author@example.com')
        comments = [frappe._dict(name='C-2', content='<p>Hello <strong>Person</strong></p>')]
        with patch.object(frappe, 'get_all', return_value=comments):
            self.assertEqual(api.notification_comment(row, 'ANN-1'), 'C-2')
        with patch.object(frappe, 'get_all', return_value=comments * 2):
            self.assertIsNone(api.notification_comment(row, 'ANN-1'), 'Do not guess between duplicate legacy comments')

    def test_open_returns_comment_and_marks_only_selected_notification(self):
        row = frappe._dict(for_user='person@example.com', document_type='Announcements', document_name='ANN-1')
        with patch.object(frappe, 'get_doc', return_value=row), patch.object(api, '_active'), patch.object(api, 'notification_comment', return_value='C-1'), patch.object(frappe.db, 'set_value') as update, patch.object(api, '_publish_read'):
            self.assertEqual(api.open_announcement_notification('N-1'), {'announcement': 'ANN-1', 'comment': 'C-1'})
            update.assert_called_once_with('Notification Log', 'N-1', 'read', 1, update_modified=False)

    def test_native_read_override_rejects_other_recipient(self):
        with patch.object(frappe, 'get_doc', return_value=frappe._dict(for_user='other@example.com')), patch.object(frappe.db, 'set_value') as update:
            with self.assertRaises(frappe.PermissionError): api.mark_as_read('N-1')
            update.assert_not_called()

    def test_bulk_read_targets_only_session_user(self):
        with patch.object(frappe.db, 'set_value') as update, patch.object(frappe, 'publish_realtime') as publish:
            api.mark_all_as_read()
        self.assertEqual(update.call_args.args[1], {'for_user': 'person@example.com', 'read': 0})
        publish.assert_called_once_with('qcmc_notifications_read', user='person@example.com', after_commit=True)


def run_tests():
    result = unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.loadTestsFromTestCase(TestDeskNotifications))
    if not result.wasSuccessful(): raise AssertionError('Notification tests failed')
    return {'successful': True, 'tests_run': result.testsRun}


def run_live_audit():
    previous = frappe.session.user
    try:
        logs = frappe.get_all('Notification Log', filters={'document_type': ['in', ['Announcements', 'Email Queue']], 'for_user': ['not in', ['Administrator', 'Guest']]}, fields=['for_user'], order_by='creation desc', limit_page_length=1)
        user = logs[0].for_user if logs else frappe.db.get_value('User', {'name': ['not in', ['Administrator', 'Guest']], 'enabled': 1, 'user_type': 'System User'}, 'name')
        if not user:
            raise AssertionError('No ordinary Desk user to verify')
        frappe.set_user(user)
        result = api.get_notification_logs(limit=20)
        verified = 0
        for row in result['notification_logs']:
            if 'qcmc_announcement=' not in (row.get('link') or ''):
                continue
            frappe.db.savepoint('qcmc_notification_audit')
            try:
                opened = api.open_announcement_notification(row['name'])
                assert opened['announcement'] == api.announcement_target(row)
                verified += 1
            finally:
                frappe.db.rollback(save_point='qcmc_notification_audit')
        return {'ordinary_user_checked': True, 'unread_count': api.get_unread_count(),
            'logs_checked': len(result['notification_logs']),
            'open_requests_verified_without_saving_read_state': verified,
            'announcement_links': sum('qcmc_announcement=' in (row.get('link') or '') for row in result['notification_logs']),
            'override_registered': frappe.override_whitelisted_method('frappe.desk.doctype.notification_log.notification_log.get_notification_logs') == 'qcmc_logic.api.desk_notifications.get_notification_logs'}
    finally:
        frappe.set_user(previous)


def run_live_user_isolation():
    """Use uncommitted probe rows; never notify users or alter real read state."""
    previous = frappe.session.user
    first = frappe.db.get_value('User', {'name': ['not in', ['Administrator', 'Guest']], 'enabled': 1, 'user_type': 'System User'}, 'name')
    if not first:
        raise AssertionError('No ordinary Desk user to verify')
    frappe.db.savepoint('qcmc_user_isolation')
    try:
        names = [frappe.generate_hash(length=20), frappe.generate_hash(length=20)]
        for name, user in zip(names, [first, 'Administrator']):
            frappe.get_doc({'doctype': 'Notification Log', 'name': name, 'for_user': user,
                'from_user': user, 'read': 0, 'type': 'Alert', 'subject': 'Transaction-only isolation probe'}).db_insert()
        with patch.object(api, '_publish_read'):
            frappe.set_user(first)
            api.mark_as_read(names[0])
            assert frappe.db.get_value('Notification Log', names[0], 'read') == 1
            assert frappe.db.get_value('Notification Log', names[1], 'read') == 0
            frappe.set_user('Administrator')
            result = api.get_notification_logs(limit=100)
            assert all(row['for_user'] == 'Administrator' for row in result['notification_logs'])
            try:
                api.mark_as_read(names[0])
                raise AssertionError('Cross-user write was accepted')
            except frappe.PermissionError:
                pass
            api.mark_all_as_read()
            assert frappe.db.get_value('Notification Log', names[1], 'read') == 1
            return {'successful': True, 'accounts_tested': 2, 'administrator_list_personal': True,
                'other_user_read_state_preserved': True, 'cross_user_write_rejected': True, 'rolled_back': True}
    finally:
        frappe.db.rollback(save_point='qcmc_user_isolation')
        frappe.set_user(previous)
