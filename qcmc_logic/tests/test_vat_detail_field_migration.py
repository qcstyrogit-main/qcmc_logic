import json
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock, patch

import frappe
from qcmc_logic.patches.add_purchase_invoice_vat_details import execute as setup
from qcmc_logic.patches.remove_duplicate_vat_detail_cost_center import execute as cleanup


class TestVATDetailFieldMigration(TestCase):
    def test_native_field_is_not_created_again_as_custom(self):
        with patch('frappe.db', frappe._dict(exists=Mock(return_value=True))), patch(
            'qcmc_logic.patches.add_purchase_invoice_vat_details.create_custom_fields'
        ) as create, patch('frappe.clear_cache'):
            setup()
        self.assertNotIn('Purchase Invoice VAT Detail', create.call_args.args[0])

    def test_cleanup_only_removes_duplicate_metadata(self):
        db=frappe._dict(get_value=Mock(return_value=frappe._dict(fieldtype='Link',options='Cost Center')),delete=Mock())
        with patch('frappe.db',db),patch('frappe.clear_cache'):
            cleanup()
        db.delete.assert_called_once_with('Custom Field',{'dt':'Purchase Invoice VAT Detail','fieldname':'cost_center'})

    def test_cleanup_requires_matching_native_field(self):
        db=frappe._dict(get_value=Mock(return_value=None),delete=Mock())
        with patch('frappe.db',db):cleanup()
        db.delete.assert_not_called()

    def test_native_and_custom_fixtures_have_no_duplicate_fields(self):
        base=Path(__file__).parents[1]/'fixtures'
        native={(doc['name'],field['fieldname']) for doc in json.loads((base/'doctype.json').read_text()) for field in doc.get('fields',[])}
        custom={(field.get('dt'),field.get('fieldname')) for field in json.loads((base/'custom_field.json').read_text())}
        self.assertFalse(native & custom)
