import json
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from frappe import _dict

from qcmc_logic.patches import ensure_daily_job_schedule_permissions as permissions
from qcmc_logic.patches import restore_daily_job_schedule_navigation as navigation


class Row(_dict):
    def set(self, key, value):
        self[key] = value


class Document(SimpleNamespace):
    def append(self, field, values):
        row = Row(values)
        getattr(self, field).append(row)
        return row


class TestDailyJobScheduleInstallation(TestCase):
    def test_fixture_includes_foreman_access(self):
        path = Path(__file__).parents[1] / 'fixtures' / 'doctype.json'
        schedule = next(d for d in json.loads(path.read_text()) if d['name'] == 'Daily Job Schedule')
        permission = next(p for p in schedule['permissions'] if p['role'] == 'Machine Shop Foreman')
        for right in ('read', 'write', 'create', 'delete'):
            self.assertEqual(permission[right], 1)

    def test_permissions_repaired_after_fixture_import_and_on_repeat(self):
        doc = Document(permissions=[Row(role='Machine Shop Foreman', read=0)], save=Mock())
        with patch.object(permissions, 'frappe') as frappe:
            frappe.db.exists.return_value = True
            frappe.get_doc.return_value = doc
            permissions.execute()
            permissions.execute()
        self.assertEqual(len(doc.permissions), 1)
        for right in ('read', 'write', 'create', 'delete'):
            self.assertEqual(doc.permissions[0][right], 1)

    def test_after_migrate_repairs_permissions_after_fixtures(self):
        from qcmc_logic import hooks
        self.assertIn('qcmc_logic.patches.ensure_daily_job_schedule_permissions.execute', hooks.after_migrate)

    def test_workspace_available_without_sidebar_doctype_and_repeat_is_idempotent(self):
        workspace = Document(shortcuts=[], content='[]', save=Mock())
        with patch.object(navigation, 'frappe') as frappe:
            frappe.flags.in_fixtures = False
            frappe.db.exists.side_effect = lambda dt, name: (dt, name) in {
                ('DocType', 'Daily Job Schedule'), ('Workspace', 'Assets')}
            frappe.get_doc.return_value = workspace
            navigation.execute()
            navigation.execute()
            self.assertFalse(frappe.flags.in_fixtures)
        workspace.save.assert_called_once()
        self.assertEqual(len(workspace.shortcuts), 1)
        self.assertEqual(json.loads(workspace.content)[0]['data']['shortcut_name'], 'Daily Job Schedule')

    def test_existing_sidebar_and_workspace_content_preserved(self):
        original = {'id': 'existing', 'type': 'header', 'data': {'text': 'Assets'}}
        workspace = Document(shortcuts=[], content=json.dumps([original]), save=Mock())
        sidebar = Document(items=[Row(link_type='DocType', link_to='Asset')], save=Mock())
        with patch.object(navigation, 'frappe') as frappe:
            frappe.flags.in_import = False
            frappe.db.exists.return_value = True
            frappe.get_doc.side_effect = lambda dt, name: workspace if dt == 'Workspace' else sidebar
            navigation.execute()
            navigation.execute()
            self.assertFalse(frappe.flags.in_import)
        sidebar.save.assert_called_once()
        self.assertEqual(len(sidebar.items), 2)
        self.assertEqual(json.loads(workspace.content)[0], original)
