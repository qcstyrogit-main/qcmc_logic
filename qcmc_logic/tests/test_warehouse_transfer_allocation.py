import unittest
from unittest.mock import patch, Mock
import frappe


class TestTransferAllocation(unittest.TestCase):
    def doc(self, **values):
        fields = dict(name='WT-TEST', doctype='Warehouse Transfer', docstatus=0,
                      transfer_status='Draft', target_warehouse='WH', target_company='COMPANY',
                      date_transferred='2026-11-10', custom_apply_putaway_rule=1,
                      custom_storage_allocation_enabled=1,
                      transfer_items=[frappe._dict(name='ROW',item_code='ITEM',uom='PCS',issued_qty=12,received_qty=0)])
        fields.update(values)
        return frappe._dict(fields)

    def test_draft_uses_issued_quantity_and_preserves_bulk(self):
        from qcmc_logic import warehouse_transfer_allocation as wt
        doc=self.doc()
        with patch.object(wt, 'get_item', return_value=frappe._dict(stock_uom='PCS',is_stock_item=1)):
            adapter=wt.planning_document(doc)
        self.assertEqual(adapter['items'][0].qty,12)
        self.assertEqual(adapter['items'][0].warehouse,'WH')
        self.assertEqual(doc.transfer_items[0].received_qty,0)

    def test_receiving_uses_actual_quantities_including_zero(self):
        from qcmc_logic import warehouse_transfer_allocation as wt
        for qty in (0,5,15):
            doc=self.doc(docstatus=1,transfer_status='Transferred')
            doc.transfer_items[0].received_qty=qty
            with patch.object(wt, 'get_item', return_value=frappe._dict(stock_uom='PCS',is_stock_item=1)):
                self.assertEqual(wt.planning_document(doc)['items'][0].qty,qty)

    def test_priority_capacity_and_stock_unit_conversion(self):
        from qcmc_logic import warehouse_transfer_allocation as wt
        from qcmc_logic import wrr_allocation as wrr
        doc=self.doc()
        doc.transfer_items[0].uom='BOX'
        rules=[frappe._dict(name='R1',warehouse='WH',item_code='ITEM',location='A',stock_capacity=10,stock_uom='PCS',priority=1),frappe._dict(name='R2',warehouse='WH',item_code='ITEM',location='B',stock_capacity=100,stock_uom='PCS',priority=2)]
        with (patch.object(wt,'get_item',return_value=frappe._dict(stock_uom='PCS',is_stock_item=1)),
              patch.object(wt,'get_conversion_factor',return_value={'conversion_factor':2}),
              patch.object(wrr,'get_ordered_dimension_putaway_rules',return_value=(False,rules)),
              patch.object(wrr,'get_location',side_effect=lambda name:frappe._dict(disabled=0,is_group=0,custom_warehouse='WH')),
              patch.object(wrr,'get_physical_quantities',return_value={('ITEM','A','PCS'):7}),
              patch.object(wrr,'get_reserved_quantities',return_value={}) as reserved):
            rows=wt.plan_allocations(doc,'SA-OWN')['WH']
        self.assertEqual([(r['suggested_location'],r['suggested_qty']) for r in rows],[('A',3),('B',21)])
        self.assertTrue(all(r['source_doctype']=='Warehouse Transfer' and r['source_document']=='WT-TEST' for r in rows))
        self.assertEqual(reserved.call_args.kwargs['exclude_allocation'],'SA-OWN')

    def test_receive_blocks_shortage_before_writing(self):
        from qcmc_logic import warehouse_transfer_allocation as wt
        with (patch.object(wt,'linked_allocations',return_value=[]),patch.object(wt,'lock_warehouses'),
              patch.object(wt,'plan_allocations',return_value={'WH':[dict(status='UNALLOCATED',item_code='ITEM',suggested_qty=12,stock_uom='PCS')]}),
              patch.object(frappe,'get_doc') as get_doc):
            with self.assertRaises(frappe.ValidationError):
                wt.sync_allocations(self.doc(), require_complete=True)
        get_doc.assert_not_called()

    def test_unchecked_releases_draft_reservations(self):
        from qcmc_logic import warehouse_transfer_allocation as wt
        allocation=Mock(docstatus=0,warehouse='WH',name='SA-1')
        with (patch.object(wt,'linked_allocations',return_value=[allocation]),patch.object(wt,'lock_warehouses'),patch.object(wt,'plan_allocations') as plan):
            wt.sync_allocations(self.doc(custom_apply_putaway_rule=0))
        plan.assert_not_called()
        self.assertEqual(allocation.status,'Cancelled')
        allocation.set.assert_any_call('locations',[])
        allocation.save.assert_called_once()

    def test_manual_checkbox_never_forced_on(self):
        from qcmc_logic import warehouse_transfer_allocation as wt
        for checked in (0,1):
            doc=self.doc(custom_apply_putaway_rule=checked)
            wt.prepare_transfer(doc)
            self.assertEqual(doc.custom_apply_putaway_rule,checked)


def run_tests():
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(__import__(__name__,fromlist=[''])))
    if not result.wasSuccessful(): raise AssertionError('Warehouse Transfer allocation tests failed')
    return {'tests_run':result.testsRun,'successful':True}


class TestTransferAllocationGuards(unittest.TestCase):
    def test_submitted_client_cannot_disable_managed_marker(self):
        from qcmc_logic import warehouse_transfer_allocation as wt
        doc=Mock(docstatus=1)
        doc.get_doc_before_save.return_value=frappe._dict(custom_storage_allocation_enabled=1)
        doc.get.return_value=0
        doc.custom_storage_allocation_enabled=0
        wt.prepare_transfer(doc)
        self.assertEqual(doc.custom_storage_allocation_enabled,1)

    def test_transfer_owned_allocation_cannot_be_directly_changed(self):
        doc=frappe.get_doc(dict(doctype='Storage Allocation',warehouse_transfer='WT-TEST'))
        with self.assertRaises(frappe.ValidationError): doc.validate()

    def test_native_projection_rows_are_new_children(self):
        from qcmc_logic import warehouse_transfer_allocation as wt
        doc=Mock(docstatus=0)
        doc.is_new.return_value=False
        doc.get.return_value=1
        row=frappe._dict(name='SOURCE-CHILD',item_code='ITEM',status='PENDING_VERIFICATION',suggested_qty=5,suggested_location='A')
        allocation=frappe._dict(name='SA-1',warehouse='WH',locations=[row])
        with patch.object(wt,'linked_allocations',return_value=[allocation]):
            rows=wt.get_allocation_grid_rows(doc)
        self.assertNotIn('name',rows[0], 'Projection children must not reuse source-child database identities')
        projection=frappe.get_doc(dict(doctype='Warehouse Transfer',custom_storage_allocation=rows))
        self.assertTrue(projection.custom_storage_allocation[0].is_new())

    def test_receive_uses_owner_authorization_for_linked_submit(self):
        from qcmc_logic import warehouse_transfer_allocation as wt
        doc=frappe.get_doc(dict(doctype='Warehouse Transfer',name='WT-TEST',custom_storage_allocation_enabled=1))
        allocation=Mock(docstatus=0,locations=[],flags=frappe._dict())
        with (patch.object(wt,'linked_allocations',return_value=[allocation]),
              patch.object(wt.wrr,'_write') as write):
            wt.submit_allocations(doc)
        self.assertTrue(allocation.flags.ignore_permissions)
        write.assert_called_once_with(allocation,'submit')

    def test_historical_submitted_transfer_cannot_change_stock_unit_semantics(self):
        from qcmc_logic import warehouse_transfer_allocation as wt
        doc=Mock(docstatus=1)
        doc.get_doc_before_save.return_value=frappe._dict(custom_storage_allocation_enabled=0)
        doc.get.return_value=1
        with self.assertRaises(frappe.ValidationError): wt.prepare_transfer(doc)
