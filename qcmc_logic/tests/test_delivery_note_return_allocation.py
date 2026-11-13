import unittest
from unittest.mock import patch, Mock
import frappe


class TestReturnAllocation(unittest.TestCase):
    def doc(self, **kwargs):
        values=dict(doctype='Delivery Note',name='DN-RETURN',is_return=1,docstatus=0,
                    custom_apply_putaway_rule=1,custom_storage_allocation_enabled=1,company='COMPANY',
                    posting_date='2026-11-10',posting_time='12:00:00',
                    items=[frappe._dict(name='ROW',item_code='ITEM',qty=-12,conversion_factor=2,stock_uom='PCS',warehouse='WH',is_stock_item=1)])
        values.update(kwargs)
        return frappe._dict(values)

    def test_return_reuses_priority_capacity_and_converts_negative_bulk_qty(self):
        from qcmc_logic import delivery_note_return_allocation as dn
        from qcmc_logic import wrr_allocation as wrr
        doc=self.doc()
        rules=[frappe._dict(name='R1',item_code='ITEM',warehouse='WH',location='A',stock_capacity=10,stock_uom='PCS',priority=1),frappe._dict(name='R2',item_code='ITEM',warehouse='WH',location='B',stock_capacity=20,stock_uom='PCS',priority=2)]
        with (patch.object(wrr,'get_ordered_dimension_putaway_rules',return_value=(False,rules)),
              patch.object(wrr,'get_location',side_effect=lambda name:frappe._dict(disabled=0,is_group=0,custom_warehouse='WH')),
              patch.object(wrr,'get_physical_quantities',return_value={('ITEM','A','PCS'):7}),
              patch.object(wrr,'get_reserved_quantities',return_value={}) as reserved):
            rows=dn.plan_allocations(doc,{'WH':'SA-OWN'})['WH']
        self.assertEqual([(r['suggested_location'],r['suggested_qty']) for r in rows],[('A',3),('B',20),('',1)])
        self.assertTrue(all(r['source_doctype']=='Delivery Note' and r['source_document']=='DN-RETURN' for r in rows))
        self.assertEqual(doc['items'][0].qty,-12)
        self.assertEqual(reserved.call_args.kwargs['exclude_allocation'],'SA-OWN')

    def test_outbound_does_not_use_return_allocation(self):
        from qcmc_logic import delivery_note_return_allocation as dn
        self.assertFalse(dn.uses_allocation(self.doc(is_return=0)))

    def test_unchecked_releases_saved_reservations(self):
        from qcmc_logic import delivery_note_return_allocation as dn
        allocation=Mock(docstatus=0,warehouse='WH',name='SA-1')
        with (patch.object(dn,'linked_allocations',return_value=[allocation]),patch.object(dn,'lock_warehouses'),patch.object(dn,'plan_allocations') as plan):
            dn.sync_allocations(self.doc(custom_apply_putaway_rule=0))
        plan.assert_not_called()
        self.assertEqual(allocation.status,'Cancelled')
        allocation.set.assert_any_call('locations',[])

    def test_submit_shortage_blocks_before_allocation_write(self):
        from qcmc_logic import delivery_note_return_allocation as dn
        shortage=dict(item_code='ITEM',suggested_qty=1,stock_uom='PCS',status='UNALLOCATED')
        with (patch.object(dn,'linked_allocations',return_value=[]),patch.object(dn,'lock_warehouses'),
              patch.object(dn,'plan_allocations',return_value={'WH':[shortage]}),patch.object(frappe,'get_doc') as get_doc):
            with self.assertRaises(frappe.ValidationError): dn.sync_allocations(self.doc(),require_complete=True)
        get_doc.assert_not_called()

    def test_return_owned_allocation_rejects_direct_writes(self):
        doc=frappe.get_doc(dict(doctype='Storage Allocation',delivery_note='DN-RETURN'))
        with self.assertRaises(frappe.ValidationError): doc.validate()


def run_tests():
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(__import__(__name__,fromlist=[''])))
    if not result.wasSuccessful(): raise AssertionError('Delivery Note return allocation tests failed')
    return {'tests_run':result.testsRun,'successful':True}


class TestReturnBundles(unittest.TestCase):
    def test_bundle_component_inherits_parent_warehouse(self):
        from qcmc_logic import delivery_note_return_allocation as dn
        doc=frappe._dict(name='DN',company='CO',items=[frappe._dict(name='PARENT',item_code='BUNDLE',qty=-1,conversion_factor=1,stock_uom='SET',warehouse='WH',is_stock_item=0)],packed_items=[frappe._dict(name='PART',parent_detail_docname='PARENT',item_code='COMPONENT',qty=-3,warehouse='')])
        with patch.object(frappe,'get_cached_doc',return_value=frappe._dict(stock_uom='PCS',is_stock_item=1)):
            rows=dn.planning_document(doc)['items']
        self.assertEqual(rows[1].warehouse,'WH')
        self.assertEqual(rows[1].qty,3)
        self.assertEqual(rows[0].is_stock_item,0)


class TestReturnNativeTable(unittest.TestCase):
    def test_lazy_delivery_note_can_load_nonempty_virtual_allocation_table(self):
        from frappe.model.document import get_lazy_controller
        from qcmc_logic import delivery_note_return_allocation as dn
        controller=get_lazy_controller('Delivery Note')
        row=dict(name='ALLOCATION-ROW',item_code='ITEM',stock_quantity=2,status='Reserved')
        with patch.object(dn,'get_allocation_grid_rows',return_value=[row]):
            doc=controller(doctype='Delivery Note',name='DN-TEST',is_return=1,
                           custom_storage_allocation_enabled=1,custom_apply_putaway_rule=1)
            values=doc.as_dict()['custom_storage_allocation']
        self.assertEqual(len(values),1)
        self.assertEqual(values[0]['stock_quantity'],2)
