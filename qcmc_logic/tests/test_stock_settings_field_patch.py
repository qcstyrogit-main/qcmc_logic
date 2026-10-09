import unittest
from unittest.mock import Mock, patch

import frappe

from qcmc_logic.patches import fix_stock_settings_warehouse_access_fields as migration


class TestStockSettingsFieldPatch(unittest.TestCase):
    def run_patch(self, records, standard_fields=()):
        def exists(doctype, filters):
            if doctype == 'DocType':
                return filters == 'Stock Settings'
            if isinstance(filters, str):
                return filters if filters in records else None
            return next((name for name, row in records.items() if all(row.get(k) == v for k, v in filters.items())), None)

        def get_doc(doctype, name):
            row = records[name]
            doc = Mock()
            doc.dt, doc.fieldname = row['dt'], row['fieldname']
            doc.update.side_effect = lambda values: row.update(values)
            return doc

        def create(doctype, definition, **kwargs):
            if exists('Custom Field', dict(dt=doctype, fieldname=definition['fieldname'])):
                return
            name = doctype + '-' + definition['fieldname']
            if name in records:
                raise frappe.DuplicateEntryError('Custom Field', name)
            records[name] = dict(definition, dt=doctype)

        meta = Mock(has_field=lambda fieldname: fieldname in standard_fields)
        with patch.object(migration.frappe, 'db', Mock(exists=exists)), patch.object(
            migration.frappe, 'get_meta', return_value=meta
        ), patch.object(migration.frappe, 'get_doc', side_effect=get_doc), patch.object(
            migration.frappe, 'clear_cache'
        ), patch.object(migration, 'create_custom_field', side_effect=create):
            migration.execute()

    def test_repairs_existing_name_with_mismatched_field_metadata(self):
        name = 'Stock Settings-custom_enable_global_warehouse_access'
        records = {name: dict(dt='Subcontracting Receipt Item', fieldname='incorrect_legacy_field', default='1')}
        self.run_patch(records)
        self.assertEqual(records[name]['dt'], 'Stock Settings')
        self.assertEqual(records[name]['fieldname'], 'custom_enable_global_warehouse_access')
        self.assertEqual(records[name]['default'], '1', 'Preserve existing configuration when the definition omits a default')
        self.assertEqual(len(records), 3)
        self.run_patch(records)
        self.assertEqual(len(records), 3, 'Rerunning must not create duplicates')

    def test_existing_custom_fields_are_reused_despite_stale_meta(self):
        records = {f'Stock Settings-{field}': dict(definition, dt='Stock Settings') for field, definition in migration.STOCK_SETTINGS_FIELDS.items()}
        self.run_patch(records)
        self.assertEqual(len(records), 3)

    def test_missing_fields_are_created_once(self):
        records = {}
        self.run_patch(records)
        self.run_patch(records)
        self.assertEqual(len(records), 3)

    def test_existing_field_with_noncanonical_name_is_reused(self):
        records = {'legacy-field-record': dict(dt='Stock Settings', fieldname='custom_enable_global_warehouse_access')}
        self.run_patch(records)
        self.assertNotIn('Stock Settings-custom_enable_global_warehouse_access', records)
        self.assertEqual(len(records), 3)


def run_tests():
    result = unittest.TextTestRunner().run(unittest.defaultTestLoader.loadTestsFromTestCase(TestStockSettingsFieldPatch))
    if not result.wasSuccessful():
        raise AssertionError('Stock Settings field patch tests failed')
    return {'tests_run': result.testsRun, 'successful': True}
