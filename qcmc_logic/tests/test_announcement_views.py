import unittest
from unittest.mock import Mock, patch

import frappe

from qcmc_logic.api import login_notices
from qcmc_logic.qcmc_logics.doctype.announcement_view.announcement_view import AnnouncementView


class TestAnnouncementViews(unittest.TestCase):
    def test_primary_key_is_unique_per_announcement_and_user(self):
        def key(announcement, viewer):
            doc = frappe._dict(announcement=announcement, viewer=viewer)
            AnnouncementView.autoname(doc)
            return doc.name

        self.assertEqual(key('ANN-1', 'first@example.com'), key('ANN-1', 'first@example.com'))
        self.assertNotEqual(key('ANN-1', 'first@example.com'), key('ANN-1', 'second@example.com'))
        self.assertNotEqual(key('ANN-1', 'first@example.com'), key('ANN-2', 'first@example.com'))

    def test_guest_cannot_record_views(self):
        with patch.object(frappe, 'session', frappe._dict(user='Guest')):
            with self.assertRaises(frappe.PermissionError):
                login_notices.record_announcement_view('ANN-00001')

    def test_inactive_announcements_cannot_be_counted(self):
        for overrides in [dict(published=0), dict(publish_from='2999-01-01'), dict(publish_to='2000-01-01')]:
            announcement = frappe._dict(published=1, publish_from=None, publish_to=None)
            announcement.update(overrides)
            with patch.object(frappe, 'session', frappe._dict(user='employee@example.com')), patch.object(
                frappe, 'get_doc', return_value=announcement
            ):
                with self.assertRaises(frappe.PermissionError):
                    login_notices.record_announcement_view('ANN-00001')

    def test_view_uses_session_identity_and_idempotent_insert(self):
        announcement = frappe._dict(published=1, publish_from=None, publish_to=None)
        view = Mock()
        with patch.object(frappe, 'session', frappe._dict(user='employee@example.com')), patch.object(
            frappe, 'get_doc', side_effect=[announcement, view]
        ) as get_doc, patch.object(frappe, 'db', Mock(count=Mock(return_value=12), exists=Mock(return_value=None))):
            result = login_notices.record_announcement_view('ANN-00001')
        self.assertEqual(result, {'views': 12})
        self.assertEqual(get_doc.call_args.args[0]['viewer'], 'employee@example.com')
        view.insert.assert_called_once_with(ignore_permissions=True, ignore_if_duplicate=True)

    def test_existing_view_after_rename_is_not_counted_again(self):
        announcement = frappe._dict(published=1, publish_from=None, publish_to=None)
        with patch.object(frappe, 'session', frappe._dict(user='renamed@example.com')), patch.object(
            frappe, 'get_doc', return_value=announcement
        ) as get_doc, patch.object(frappe, 'db', Mock(count=Mock(return_value=1), exists=Mock(return_value='original-hash'))):
            self.assertEqual(login_notices.record_announcement_view('RENAMED-ANN'), {'views': 1})
        get_doc.assert_called_once_with('Announcements', 'RENAMED-ANN')

    def test_totals_do_not_expose_viewer_identities(self):
        rows = [{'name': 'ANN-1'}, {'name': 'ANN-2'}]
        with patch.object(frappe, 'db', Mock(sql=Mock(return_value=[frappe._dict(announcement='ANN-1', views=2)]))):
            login_notices._add_announcement_view_counts(rows)
        self.assertEqual(rows, [{'name': 'ANN-1', 'views': 2}, {'name': 'ANN-2', 'views': 0}])


def run_tests():
    result = unittest.TextTestRunner().run(unittest.defaultTestLoader.loadTestsFromTestCase(TestAnnouncementViews))
    if not result.wasSuccessful():
        raise AssertionError('Announcement view tests failed')
    return {'tests_run': result.testsRun, 'successful': True}
