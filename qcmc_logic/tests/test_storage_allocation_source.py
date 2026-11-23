import unittest
import frappe


class TestStorageAllocationSource(unittest.TestCase):
    def test_wrr_uses_a_generic_purchase_receipt_link(self):
        from qcmc_logic.storage_allocation_source import source_reference
        self.assertEqual(source_reference(frappe._dict(purchase_receipt='WRR-1')), dict(
            source_doctype='Purchase Receipt', source_document='WRR-1', source_document_count=1))

    def test_scanner_links_to_its_stock_entry_and_deduplicates_item_rows(self):
        from qcmc_logic.storage_allocation_source import source_reference
        doc = frappe._dict(locations=[frappe._dict(source_doctype='Stock Entry', source_document='STE-1')]*2,
                          references=[frappe._dict(reference_doctype='Stock Entry', reference_name='STE-1')])
        self.assertEqual(source_reference(doc), dict(source_doctype='Stock Entry', source_document='STE-1', source_document_count=1))

    def test_multiple_source_documents_are_not_mislabeled_as_one_document(self):
        from qcmc_logic.storage_allocation_source import source_reference
        doc = frappe._dict(references=[frappe._dict(reference_doctype='Stock Entry', reference_name=name) for name in ('STE-1','STE-2')])
        self.assertEqual(source_reference(doc), dict(source_doctype='Stock Entry', source_document=None, source_document_count=2))

    def test_other_receiving_document_types_are_supported(self):
        from qcmc_logic.storage_allocation_source import source_reference
        for doctype in ('Warehouse Transfer','Delivery Note','Sales Invoice'):
            with self.subTest(doctype=doctype):
                doc = frappe._dict(references=[frappe._dict(reference_doctype=doctype, reference_name='DOC-1')])
                self.assertEqual(source_reference(doc)['source_doctype'], doctype)
                self.assertEqual(source_reference(doc)['source_document'], 'DOC-1')


def run_tests():
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(TestStorageAllocationSource))
    if not result.wasSuccessful():
        raise AssertionError('Storage Allocation source tests failed')
    return {'tests_run':result.testsRun,'successful':True}
