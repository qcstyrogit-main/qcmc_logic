import unittest
from unittest.mock import patch
import frappe


class TestStorageAllocationRename(unittest.TestCase):
    def test_renames_existing_doctype_without_merging_or_changing_record_names(self):
        from qcmc_logic.patches import rename_warehouse_allocation as migration
        with (patch.object(frappe.db, 'exists', side_effect=[True, False]),
              patch.object(migration, 'rename_doc') as rename,
              patch.object(migration, 'update_workspace_references'),
              patch.object(frappe, 'clear_cache')):
            migration.execute()
        rename.assert_called_once_with('DocType', 'Warehouse Allocation', 'Storage Allocation',
                                       force=True, ignore_permissions=True, show_alert=False, rebuild_search=False)

    def test_rerun_leaves_existing_storage_allocation_intact(self):
        from qcmc_logic.patches import rename_warehouse_allocation as migration
        with (patch.object(frappe.db, 'exists', side_effect=[False, True]),
              patch.object(migration, 'rename_doc') as rename,
              patch.object(migration, 'update_workspace_references'), patch.object(frappe, 'clear_cache')):
            migration.execute()
        rename.assert_not_called()

    def test_existing_old_and_new_doctypes_block_unsafe_merge(self):
        from qcmc_logic.patches import rename_warehouse_allocation as migration
        with (patch.object(frappe.db, 'exists', return_value=True), patch.object(migration, 'rename_doc') as rename):
            with self.assertRaises(frappe.ValidationError):
                migration.execute()
        rename.assert_not_called()


    def test_resume_after_rename_finishes_display_references(self):
        from qcmc_logic.patches import rename_warehouse_allocation as migration
        with (patch.object(frappe.db, 'exists', side_effect=[False, True]),
              patch.object(migration, 'update_workspace_references') as update,
              patch.object(frappe, 'clear_cache')):
            migration.execute()
        update.assert_called_once()

    def test_existing_wrr_field_labels_are_renamed_by_this_patch(self):
        from qcmc_logic.patches import rename_warehouse_allocation as migration
        with (patch.object(frappe.db, 'table_exists', return_value=False),
              patch.object(frappe.db, 'set_value') as update,
              patch.object(frappe, 'get_all', return_value=[])):
            migration.update_workspace_references()
        update.assert_any_call('Custom Field', {'dt': 'Purchase Receipt',
            'fieldname': ['in', ['custom_warehouse_allocation_section', 'custom_warehouse_allocation']],
            'label': 'Warehouse Allocation'}, 'label', 'Storage Allocation', update_modified=False)


def run_tests():
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(TestStorageAllocationRename))
    if not result.wasSuccessful():
        raise AssertionError('Storage Allocation rename tests failed')
    return {'tests_run': result.testsRun, 'successful': True}
