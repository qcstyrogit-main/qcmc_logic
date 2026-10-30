import unittest
from unittest.mock import Mock, patch

import frappe

from qcmc_logic.api import announcement_comments as api


class TestAnnouncementComments(unittest.TestCase):
    def test_mention_profile_returns_only_four_fields(self):
        comments = {'comments': [{'content': '<span class="mention" data-id="person@example.com">Person</span>'}]}
        user = frappe._dict(full_name='Person', email='person@example.com')
        employee = frappe._dict(employee_name='Employee Name', department='MIS', designation='Developer')
        with patch.object(api, 'get_comments', return_value=comments), patch.object(frappe.db, 'get_value', side_effect=[user, employee]):
            self.assertEqual(api.get_mention_profile('ANN-1', 'person@example.com'),
                {'name': 'Employee Name', 'department': 'MIS', 'position': 'Developer', 'email': 'person@example.com'})
        with patch.object(api, 'get_comments', return_value=comments), patch.object(frappe.db, 'get_value', side_effect=[user, None]):
            self.assertEqual(api.get_mention_profile('ANN-1', 'person@example.com')['department'], '')
        with patch.object(api, 'get_comments', return_value={'comments': []}):
            with self.assertRaises(frappe.PermissionError): api.get_mention_profile('ANN-1', 'other@example.com')

    def setUp(self):
        self.session = patch.object(frappe, 'session', frappe._dict(user='author@example.com'))
        self.session.start(); self.addCleanup(self.session.stop)
        self.roles = patch.object(frappe, 'get_roles', return_value=[])
        self.roles.start(); self.addCleanup(self.roles.stop)
        self.active = frappe._dict(published=1, publish_from=None, publish_to=None)

    def test_guest_and_inactive_announcements_are_rejected(self):
        frappe.session.user = 'Guest'
        with self.assertRaises(frappe.PermissionError):
            api.get_comments('ANN-1')
        frappe.session.user = 'author@example.com'
        for changes in [dict(published=0), dict(publish_from='2999-01-01'), dict(publish_to='2000-01-01')]:
            doc = self.active.copy(); doc.update(changes)
            with patch.object(frappe, 'get_doc', return_value=frappe._dict(doc)):
                with self.assertRaises(frappe.PermissionError): api.get_comments('ANN-1')

    def test_create_uses_session_identity_and_checks_reply_announcement(self):
        saved = Mock(name='C-NEW'); saved.name = 'C-NEW'
        parent = frappe._dict(name='C-1', reference_doctype='Announcements', reference_name='ANN-1', comment_type='Comment')
        # Availability is covered separately. Isolate it here so a cold system
        # timezone cache cannot consume this test's mocked document reads.
        with patch.object(api, '_active'), patch.object(frappe, 'get_doc', side_effect=[parent, saved]) as get_doc, patch.object(frappe, 'db', Mock(count=Mock(return_value=2))):
            result = api.add_comment('ANN-1', '<p>Hello</p>', parent='C-1')
        values = get_doc.call_args.args[0]
        self.assertEqual(values['comment_email'], frappe.session.user)
        self.assertEqual(values['subject'], api.REPLY_PREFIX + 'C-1')
        saved.insert.assert_called_once_with(ignore_permissions=True)
        self.assertEqual(result['count'], 2)
        parent.reference_name = 'OTHER'
        with patch.object(api, '_active'), patch.object(frappe, 'get_doc', side_effect=[parent]):
            with self.assertRaises(frappe.PermissionError): api.add_comment('ANN-1', 'Reply', parent='C-1')

    def test_sanitizes_html_and_rejects_empty_or_excessive_content(self):
        result = api._clean_content('<p onclick="alert(1)">Safe<script>alert(1)</script></p>')
        self.assertNotIn('onclick', result); self.assertNotIn('<script', result)
        for value in ['<p><br></p>', ' ' * 20, 'x' * 30001]:
            with self.assertRaises(frappe.ValidationError): api._clean_content(value)
        self.assertNotIn('class="mention"', api._clean_content('<span class="mention">Invalid mention</span>'))

    def test_only_author_or_moderator_can_edit_or_delete(self):
        comment = frappe._dict(name='C-1', owner='other@example.com', reference_doctype='Announcements', reference_name='ANN-1', comment_type='Comment')
        with patch.object(frappe, 'get_doc', side_effect=[comment, self.active]):
            with self.assertRaises(frappe.PermissionError): api.update_comment('C-1', 'Changed')
        with patch.object(frappe, 'get_doc', side_effect=[comment, self.active]), patch.object(frappe, 'delete_doc') as delete:
            with self.assertRaises(frappe.PermissionError): api.delete_comment('C-1')
            delete.assert_not_called()
        with patch.object(frappe, 'get_roles', return_value=['System Manager']):
            self.assertTrue(api._can_manage(comment))
        comment.owner = frappe.session.user
        self.assertTrue(api._can_manage(comment))

    def test_unrelated_comment_types_are_rejected(self):
        for changes in [dict(reference_doctype='Sales Invoice'), dict(comment_type='Like')]:
            comment = frappe._dict(reference_doctype='Announcements', reference_name='ANN-1', comment_type='Comment'); comment.update(changes)
            with patch.object(frappe, 'get_doc', return_value=comment):
                with self.assertRaises(frappe.PermissionError): api.delete_comment('C-1')

    def test_delete_keeps_replies_and_returns_actual_count(self):
        comment = frappe._dict(name='C-1', owner=frappe.session.user, reference_doctype='Announcements', reference_name='ANN-1', comment_type='Comment')
        with patch.object(frappe, 'get_doc', side_effect=[comment, self.active]), patch.object(frappe, 'delete_doc') as delete, patch.object(frappe, 'db', Mock(count=Mock(return_value=3))):
            self.assertEqual(api.delete_comment('C-1'), {'count': 3})
        delete.assert_called_once_with('Comment', 'C-1', ignore_permissions=True)

    def test_read_returns_reply_parent_and_per_comment_permissions(self):
        rows = [frappe._dict(name='C-1', owner=frappe.session.user, comment_by=None, subject=None, content='<p>Hi</p>', creation='2026-10-15', modified='2026-10-15'),
                frappe._dict(name='C-2', owner='other@example.com', comment_by='Other', subject=api.REPLY_PREFIX + 'C-1', content='<p>Reply</p>', creation='2026-10-16', modified='2026-10-16')]
        with patch.object(frappe, 'get_doc', return_value=self.active), patch.object(frappe, 'get_all', return_value=rows), patch.object(api, 'get_fullname', return_value='Author'), patch.object(frappe, 'get_cached_value', return_value='/files/profile.jpg'):
            result = api.get_comments('ANN-1')
        self.assertEqual(result['count'], 2)
        self.assertTrue(result['comments'][0]['can_manage'])
        self.assertFalse(result['comments'][1]['can_manage'])
        self.assertEqual(result['comments'][1]['parent'], 'C-1')
        self.assertEqual(result['comments'][0]['author_image'], '/files/profile.jpg')

    def test_edit_notifies_only_new_mentions(self):
        comment = Mock(owner=frappe.session.user, reference_doctype='Announcements', reference_name='ANN-1', comment_type='Comment', content='<span class="mention" data-id="old@example.com">Old</span>')
        content = '<p><span class="mention" data-id="old@example.com">Old</span> and <span class="mention" data-id="new@example.com">New</span></p>'
        with patch.object(frappe, 'get_doc', side_effect=[comment, self.active]), patch.object(frappe, 'db', Mock(count=Mock(return_value=1))), patch.object(api, 'notify_mentions') as notify:
            api.update_comment('C-1', content)
        comment.save.assert_called_once_with(ignore_permissions=True)
        from frappe.desk.notifications import extract_mentions
        self.assertEqual(extract_mentions(notify.call_args.args[2]), ['new@example.com'])

    def test_mention_notification_opens_popup_instead_of_admin_form(self):
        doc = frappe._dict(type='Mention', document_type='Announcements', document_name='ANN 1/2', link=None)
        with patch.object(frappe.utils, 'get_url', side_effect=lambda path: 'https://erp.example' + path):
            api.link_mention_notification(doc)
        self.assertEqual(doc.link, 'https://erp.example/desk?qcmc_announcement=ANN%201%2F2')
        ordinary = frappe._dict(type='Mention', document_type='Sales Invoice', document_name='INV-1', link=None)
        api.link_mention_notification(ordinary)
        self.assertIsNone(ordinary.link)
        doc.link = '/custom-link'; api.link_mention_notification(doc)
        self.assertEqual(doc.link, '/custom-link')

    def test_saved_mentions_carry_the_server_comment_identity(self):
        comment = frappe._dict(name='C-1', reference_doctype='Announcements', reference_name='ANN-1', comment_type='Comment',
            content='<span class="mention" data-id="person@example.com" data-qcmc-comment="FORGED">Person</span>')
        api.stamp_comment_mentions(comment)
        self.assertIn('data-qcmc-comment="C-1"', comment.content)
        self.assertNotIn('FORGED', comment.content)
        notification = frappe._dict(type='Mention', document_type='Announcements', document_name='ANN-1', email_content=comment.content)
        with patch.object(frappe.db, 'get_value', return_value=frappe._dict(reference_doctype='Announcements', reference_name='ANN-1', comment_type='Comment')), patch.object(frappe.utils, 'get_url', side_effect=lambda path: path):
            api.link_mention_notification(notification)
        self.assertIn('qcmc_comment=C-1', notification.link)

    def test_realtime_invalidation_is_committed_and_exposes_no_comment_content(self):
        comment = frappe._dict(reference_doctype='Announcements', reference_name='ANN-1', comment_type='Comment', content='Private body', owner='author@example.com')
        with patch.object(frappe, 'db', Mock(get_value=Mock(return_value=self.active))), patch.object(frappe, 'publish_realtime') as publish:
            api.publish_comment_change(comment, 'on_update')
            publish.assert_called_once_with(api.CHANGE_EVENT, {'announcement': 'ANN-1'}, after_commit=True)
        for changes in [dict(published=0), dict(publish_to='2000-01-01')]:
            inactive = self.active.copy(); inactive.update(changes)
            with patch.object(frappe, 'db', Mock(get_value=Mock(return_value=frappe._dict(inactive)))), patch.object(frappe, 'publish_realtime') as publish:
                api.publish_comment_change(comment, 'after_delete'); publish.assert_not_called()
        comment.comment_type = 'Like'
        with patch.object(frappe, 'publish_realtime') as publish:
            api.publish_comment_change(comment); publish.assert_not_called()


def run_tests():
    result = unittest.TextTestRunner().run(unittest.defaultTestLoader.loadTestsFromTestCase(TestAnnouncementComments))
    if not result.wasSuccessful(): raise AssertionError('Announcement comment tests failed')
    return {'tests_run': result.testsRun, 'successful': True}


def run_live_smoke():
    """Exercise real Comment hooks, then roll back all test records/events."""
    previous_user = frappe.session.user
    frappe.set_user('Administrator')
    try:
        announcement = frappe.get_doc({'doctype': 'Announcements',
            'title': '__Announcement discussion smoke test', 'announcement': '<p>Test only</p>',
            'published': 1}).insert(ignore_permissions=True)
        ordinary_user = next((user for user in frappe.get_all('User',
            filters={'enabled': 1, 'user_type': 'System User', 'name': ['not in', ['Administrator', 'Guest']]},
            pluck='name', limit_page_length=100)
            if 'System Manager' not in frappe.get_roles(user)
            and not frappe.has_permission('Announcements', 'read', user=user)), None)
        if ordinary_user:
            frappe.set_user(ordinary_user)
        first = api.add_comment(announcement.name, '<p>First comment</p>')
        reply = api.add_comment(announcement.name, '<p>Reply</p>', parent=first['name'])
        api.update_comment(first['name'], '<p>Edited comment</p>')
        announcement.add_comment('Comment', text='Form timeline comment')
        comments = api.get_comments(announcement.name)
        assert comments['count'] == 3
        assert next(row for row in comments['comments'] if row['name'] == reply['name'])['parent'] == first['name']
        counts = [{'name': announcement.name}]; api.add_counts(counts)
        assert counts[0]['comments'] == 3
        assert api.delete_comment(first['name'])['count'] == 2
        assert any(row['name'] == reply['name'] for row in api.get_comments(announcement.name)['comments'])
        assert any(event[0] == api.CHANGE_EVENT and event[1] == {'announcement': announcement.name}
            for event in getattr(frappe.local, '_realtime_log', [])), 'Comment hooks must queue realtime changes after commit'
        return {'successful': True, 'rolled_back': True, 'ordinary_user_checked': bool(ordinary_user),
            'checks': ['create', 'reply', 'edit', 'timeline', 'count', 'delete']}
    finally:
        frappe.db.rollback()
        frappe.set_user(previous_user)


def run_live_mention_target():
    """Verify native document hooks without notifying anyone or saving probes."""
    from frappe.desk.doctype.notification_log.notification_log import NotificationLog
    from qcmc_logic.api import desk_notifications
    previous = frappe.session.user
    frappe.set_user('Administrator')
    try:
        announcement = frappe.get_doc({'doctype': 'Announcements', 'title': '__Mention target probe',
            'announcement': '<p>Transaction-only probe</p>', 'published': 1}).insert(ignore_permissions=True)
        with patch('frappe.core.doctype.comment.comment.notify_mentions'):
            result = api.add_comment(announcement.name, '<p>Hello <span class="mention" data-id="probe@example.invalid">Probe</span></p>')
        comment = frappe.get_doc('Comment', result['name'])
        assert f'data-qcmc-comment="{comment.name}"' in comment.content
        with patch.object(NotificationLog, 'after_insert'):
            note = frappe.get_doc({'doctype': 'Notification Log', 'for_user': 'Administrator', 'from_user': 'Administrator',
                'subject': 'Transaction-only mention probe', 'type': 'Mention', 'document_type': 'Announcements',
                'document_name': announcement.name, 'email_content': comment.content, 'read': 0}).insert(ignore_permissions=True)
        assert 'qcmc_comment=' + comment.name in note.link
        opened = desk_notifications.open_announcement_notification(note.name)
        assert opened == {'announcement': announcement.name, 'comment': comment.name}
        assert frappe.db.get_value('Notification Log', note.name, 'read') == 1
        return {'successful': True, 'comment_hook_verified': True, 'notification_link_verified': True,
            'exact_comment_returned': True, 'selected_notification_read': True, 'rolled_back': True}
    finally:
        frappe.db.rollback()
        frappe.set_user(previous)
