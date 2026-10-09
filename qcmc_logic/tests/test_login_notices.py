import unittest
from datetime import date
from unittest.mock import Mock, patch

import frappe
from frappe.utils import getdate as real_getdate

from qcmc_logic.api import login_notices


class TestLoginNotices(unittest.TestCase):
    def test_private_image_uses_authenticated_same_origin_endpoint(self):
        with patch.object(frappe.utils, 'get_url', return_value='https://configured.erp'):
            self.assertEqual(login_notices._notice_image_url('https://configured.erp/private/files/image.jpg', 'ANN-00001'), '/api/method/qcmc_logic.api.login_notices.get_announcement_image?name=ANN-00001')
            self.assertEqual(login_notices._notice_image_url('https://configured.erp/files/image.jpg', 'ANN-00001'), '/files/image.jpg')
            self.assertEqual(login_notices._notice_image_url('https://external.example/image.jpg', 'ANN-00001'), 'https://external.example/image.jpg')

    def test_image_endpoint_serves_active_attachment_without_doctype_read_permission(self):
        announcement = frappe._dict(published=1, publish_from=None, publish_to=None, image='/private/files/image.jpg')
        file = Mock(file_name='image.jpg', get_content=Mock(return_value=b'image-bytes'))
        with patch.object(frappe, 'session', frappe._dict(user='employee@example.com')), patch.object(
            frappe, 'get_doc', side_effect=[announcement, file]
        ), patch.object(frappe, 'db', Mock(get_value=Mock(return_value='FILE-1'))):
            response = login_notices.get_announcement_image('ANN-00001')
        self.assertEqual(response.data, b'image-bytes')
        self.assertEqual(response.mimetype, 'image/jpeg')
        self.assertEqual(response.headers['Cache-Control'], 'private, no-store')
        file.get_content.assert_called_once_with(encodings=[])

    def test_image_endpoint_rejects_guest_inactive_and_unattached_images(self):
        with patch.object(frappe, 'session', frappe._dict(user='Guest')):
            with self.assertRaises(frappe.PermissionError):
                login_notices.get_announcement_image('ANN-00001')
        for overrides in [dict(published=0), dict(publish_from='2999-01-01'), dict(publish_to='2000-01-01'), dict(image='/files/public.jpg')]:
            announcement = frappe._dict(published=1, publish_from=None, publish_to=None, image='/private/files/image.jpg')
            announcement.update(overrides)
            with patch.object(frappe, 'session', frappe._dict(user='employee@example.com')), patch.object(frappe, 'get_doc', return_value=announcement):
                with self.assertRaises(frappe.PermissionError):
                    login_notices.get_announcement_image('ANN-00001')
        announcement = frappe._dict(published=1, publish_from=None, publish_to=None, image='/private/files/image.jpg')
        with patch.object(frappe, 'session', frappe._dict(user='employee@example.com')), patch.object(frappe, 'get_doc', return_value=announcement), patch.object(frappe, 'db', Mock(get_value=Mock(return_value=None))):
            with self.assertRaises(frappe.PermissionError):
                login_notices.get_announcement_image('ANN-00001')

    def test_session_marker_changes_only_when_login_session_changes(self):
        with patch.object(login_notices.frappe, "session", frappe._dict(user="employee@example.com", sid="first")):
            first, refresh = {}, {}
            login_notices.extend_bootinfo(first)
            login_notices.extend_bootinfo(refresh)
            self.assertEqual(first, refresh)
            self.assertNotIn("first", first["qcmc_login_notice_session"])
            login_notices.frappe.session.sid = "second"
            second = {}
            login_notices.extend_bootinfo(second)
            self.assertNotEqual(first, second)

    def test_monthly_payload_excludes_new_joiners_and_birth_years(self):
        people = [
            dict(name="EMP-1", employee_name="Birthday", department="MIS", date_of_birth=date(1990, 10, 31), date_of_joining=None, user_id="birthday@example.com"),
            dict(name="EMP-2", employee_name="Veteran", department="MIS", date_of_birth=None, date_of_joining=date(2020, 10, 31), user_id=None),
            dict(name="EMP-3", employee_name="New", date_of_birth=None, date_of_joining=date(2026, 10, 1), user_id=None),
            dict(name="EMP-4", employee_name="Future", date_of_birth=None, date_of_joining=date(2027, 10, 1), user_id=None),
        ]
        with patch.object(login_notices, "getdate", side_effect=lambda value=None: real_getdate(value) if value else date(2026, 10, 8)), patch.object(
            login_notices.frappe, "db", Mock(sql=Mock(return_value=people))
        ), patch.object(login_notices.frappe, "get_installed_apps", return_value=["company_messenger"]), patch.object(
            login_notices, "list_active_announcements", return_value={"items": [], "total": 0}
        ), patch.object(login_notices.frappe, "session", frappe._dict(user="Administrator")):
            result = login_notices.get_login_notices()
        self.assertEqual(result["birthdays"], [dict(employee_id="EMP-1", employee_name="Birthday", department="MIS", day=31, user_id="birthday@example.com")])
        self.assertEqual(result["anniversaries"], [dict(employee_id="EMP-2", employee_name="Veteran", department="MIS", day=31, years=6, user_id=None)])
        self.assertTrue(result["can_greet"])
        self.assertEqual(result["month"], 10)
        self.assertEqual(result["year"], 2026)

    def test_guest_cannot_read_notices(self):
        with patch.object(login_notices.frappe, "session", frappe._dict(user="Guest")):
            with self.assertRaises(frappe.PermissionError):
                login_notices.get_login_notices()

    def test_employee_without_tweet_permission_cannot_get_recipient_accounts(self):
        people = [dict(name="EMP-1", employee_name="Birthday", department="MIS", date_of_birth=date(1990, 10, 31), date_of_joining=None, user_id="birthday@example.com")]
        with patch.object(login_notices, "getdate", side_effect=lambda value=None: real_getdate(value) if value else date(2026, 10, 8)), patch.object(
            login_notices.frappe, "db", Mock(sql=Mock(return_value=people))
        ), patch.object(login_notices.frappe, "get_installed_apps", return_value=["company_messenger"]), patch.object(
            login_notices.frappe, "get_roles", return_value=["Employee"]
        ), patch.object(login_notices, "list_active_announcements", return_value={"items": [], "total": 0}), patch.object(
            login_notices.frappe, "session", frappe._dict(user="employee@example.com")
        ):
            result = login_notices.get_login_notices()
        self.assertFalse(result["can_greet"])
        self.assertIsNone(result["birthdays"][0]["user_id"])


def run_tests():
    result = unittest.TextTestRunner().run(unittest.defaultTestLoader.loadTestsFromTestCase(TestLoginNotices))
    if not result.wasSuccessful():
        raise AssertionError("Login notice tests failed")
    return {"tests_run": result.testsRun, "successful": True}
