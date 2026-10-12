import unittest
from unittest.mock import Mock, patch

import frappe

from qcmc_logic.patches import repair_social_contact_dependency as repair


class TestSocialContactDependency(unittest.TestCase):
    def test_available_child_table_is_preserved(self):
        with patch.object(frappe, 'db', Mock(exists=Mock(return_value=True))), patch.object(
            frappe, 'clear_cache'
        ), patch.object(frappe, 'delete_doc') as delete, patch.object(frappe, 'reload_doc') as reload:
            self.assertEqual(repair.execute()['action'], 'already_available')
        delete.assert_not_called()
        reload.assert_not_called()

    def test_installed_chat_schema_is_restored_from_its_own_app(self):
        def exists(doctype, name):
            return doctype == 'Custom Field'
        with patch.object(frappe, 'db', Mock(exists=exists)), patch.object(
            frappe, 'get_installed_apps', return_value=['clefincode_chat']
        ), patch.object(frappe, 'get_app_path', return_value='/app/social_contact.json'), patch.object(
            repair.Path, 'is_file', return_value=True
        ), patch.object(frappe, 'reload_doc') as reload, patch.object(
            frappe, 'delete_doc'
        ) as delete, patch.object(frappe, 'clear_cache'):
            self.assertEqual(repair.execute()['action'], 'restored')
        reload.assert_called_once_with('clefincode_chat', 'doctype', 'social_contact', force=True)
        delete.assert_not_called()

    def test_orphan_field_is_removed_when_its_child_schema_is_unavailable(self):
        def exists(doctype, name):
            return 'Contact-social_contact' if doctype == 'Custom Field' else False
        with patch.object(frappe, 'db', Mock(exists=exists)), patch.object(
            frappe, 'get_installed_apps', return_value=['frappe', 'qcmc_logic']
        ), patch.object(frappe, 'delete_doc') as delete, patch.object(frappe, 'clear_cache'):
            self.assertEqual(repair.execute()['action'], 'removed_orphan_field')
        delete.assert_called_once_with('Custom Field', 'Contact-social_contact', ignore_permissions=True, force=True)

    def test_no_orphan_is_a_noop(self):
        with patch.object(frappe, 'db', Mock(exists=Mock(return_value=False))), patch.object(
            frappe, 'get_installed_apps', return_value=[]
        ), patch.object(frappe, 'delete_doc') as delete, patch.object(frappe, 'clear_cache'):
            self.assertEqual(repair.execute()['action'], 'nothing_to_repair')
        delete.assert_not_called()

    def test_chat_version_without_child_schema_removes_only_orphan(self):
        def exists(doctype, name):
            return 'Contact-social_contact' if doctype == 'Custom Field' else False
        with patch.object(frappe, 'db', Mock(exists=exists)), patch.object(
            frappe, 'get_installed_apps', return_value=['clefincode_chat']
        ), patch.object(frappe, 'get_app_path', return_value='/app/social_contact.json'), patch.object(
            repair.Path, 'is_file', return_value=False
        ), patch.object(frappe, 'reload_doc') as reload, patch.object(
            frappe, 'delete_doc'
        ) as delete, patch.object(frappe, 'clear_cache'):
            self.assertEqual(repair.execute()['action'], 'removed_orphan_field')
        reload.assert_not_called()
        delete.assert_called_once_with('Custom Field', 'Contact-social_contact', ignore_permissions=True, force=True)


def run_tests():
    result = unittest.TextTestRunner().run(unittest.defaultTestLoader.loadTestsFromTestCase(TestSocialContactDependency))
    if not result.wasSuccessful():
        raise AssertionError('Social Contact dependency tests failed')
    return {'tests_run': result.testsRun, 'successful': True}
