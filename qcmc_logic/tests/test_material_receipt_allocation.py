import unittest
from unittest.mock import Mock, patch
import frappe


class TestMaterialReceiptAllocation(unittest.TestCase):
    def doc(self, **kwargs):
        data=dict(doctype='Stock Entry',name='SE-TEST',stock_entry_type='Material Receipt',purpose='Material Receipt',docstatus=0,custom_storage_allocation_enabled=1,apply_putaway_rule=1,company='COMPANY',posting_date='2026-11-10',posting_time='12:00:00',items=[frappe._dict(name='ROW',item_code='ITEM',qty=12,conversion_factor=2,stock_uom='PCS',t_warehouse='WH')])
        data.update(kwargs)
        return frappe._dict(data)

    def test_gate_is_exact_material_receipt_type(self):
        from qcmc_logic import material_receipt_allocation as se
        for other in ('Manufacture','Material Transfer','Repack','Custom Receipt'):
            self.assertFalse(se.is_material_receipt(self.doc(stock_entry_type=other)))
        with patch.object(frappe,'get_cached_value',return_value='Material Receipt'):
            self.assertTrue(se.is_material_receipt(self.doc(purpose='stale')))

    def test_priority_capacity_and_bulk_stock_quantities(self):
        from qcmc_logic import material_receipt_allocation as se
        from qcmc_logic import wrr_allocation as wrr
        doc=self.doc()
        rules=[frappe._dict(name='R1',item_code='ITEM',warehouse='WH',location='A',stock_capacity=10,stock_uom='PCS',priority=1),frappe._dict(name='R2',item_code='ITEM',warehouse='WH',location='B',stock_capacity=20,stock_uom='PCS',priority=2)]
        with (patch.object(wrr,'get_ordered_dimension_putaway_rules',return_value=(False,rules)),patch.object(wrr,'get_location',side_effect=lambda name:frappe._dict(disabled=0,is_group=0,custom_warehouse='WH')),patch.object(wrr,'get_physical_quantities',return_value={('ITEM','A','PCS'):7}),patch.object(wrr,'get_reserved_quantities',return_value={}) as reserved):
            rows=se.plan_allocations(doc,{'WH':'SA-OWN'})['WH']
        self.assertEqual([(r['suggested_location'],r['suggested_qty']) for r in rows],[('A',3),('B',20),('',1)])
        self.assertEqual(doc['items'][0].qty,12)
        self.assertTrue(all(r['source_doctype']=='Stock Entry' and r['source_document']=='SE-TEST' for r in rows))
        self.assertEqual(reserved.call_args.kwargs['exclude_allocation'],'SA-OWN')
        self.assertEqual(reserved.call_args.kwargs['exclude_stock_entry'],'SE-TEST')

    def test_unchecked_releases_own_draft_reservations(self):
        from qcmc_logic import material_receipt_allocation as se
        allocation=Mock(docstatus=0,warehouse='WH',name='SA-1')
        with (patch.object(se,'linked_allocations',return_value=[allocation]),patch.object(se,'lock_warehouses'),patch.object(se,'plan_allocations') as plan):
            se.sync_allocations(self.doc(apply_putaway_rule=0))
        plan.assert_not_called()
        self.assertEqual(allocation.status,'Cancelled')
        allocation.set.assert_any_call('locations',[])

    def test_shortage_blocks_submit_before_writing(self):
        from qcmc_logic import material_receipt_allocation as se
        row=dict(item_code='ITEM',suggested_qty=1,stock_uom='PCS',status='UNALLOCATED')
        with (patch.object(se,'linked_allocations',return_value=[]),patch.object(se,'lock_warehouses'),patch.object(se,'plan_allocations',return_value={'WH':[row]}),patch.object(frappe,'get_doc') as get_doc):
            with self.assertRaises(frappe.ValidationError): se.sync_allocations(self.doc(),require_complete=True)
        get_doc.assert_not_called()

    def test_managed_stock_entry_allocation_rejects_direct_writes(self):
        doc=frappe.get_doc(dict(doctype='Storage Allocation',stock_entry='SE-TEST'))
        with self.assertRaises(frappe.ValidationError): doc.validate()


def run_tests():
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(__import__(__name__,fromlist=[''])))
    if not result.wasSuccessful(): raise AssertionError('Material Receipt allocation tests failed')
    return {'tests_run':result.testsRun,'successful':True}


class TestMaterialReceiptNativeUI(unittest.TestCase):
    def test_checkbox_rpc_with_exact_type_preserves_bulk_rows(self):
        from qcmc_logic.overrides.putaway_rule_dimension import apply_dimension_putaway_rule
        rows=[dict(item_code='ITEM',qty=12,t_warehouse='WH')]
        result=apply_dimension_putaway_rule('Stock Entry',rows,'COMPANY',sync=True,purpose='Material Receipt',stock_entry_type='Material Receipt')
        self.assertEqual(result,rows)
        self.assertEqual(len(result),1)

    def test_lazy_stock_entry_computed_allocation_table(self):
        from frappe.model.document import get_lazy_controller
        from qcmc_logic import material_receipt_allocation as se
        controller=get_lazy_controller('Stock Entry')
        with patch.object(se,'get_allocation_grid_rows',return_value=[dict(name='ALLOCATION-ROW',item_code='ITEM',stock_quantity=12,status='Reserved')]):
            doc=controller(doctype='Stock Entry',name='SE-TEST',stock_entry_type='Material Receipt',purpose='Material Receipt')
            values=doc.as_dict()['custom_storage_allocation']
        self.assertEqual(values[0]['stock_quantity'],12)
