import unittest
from unittest.mock import patch

import frappe
from qcmc_logic import wrr_allocation as wrr


class TestWRRAllocation(unittest.TestCase):
    def doc(self, items=None):
        return frappe._dict(name='WRR-TEST', company='COMPANY', is_return=0,
                            items=items or [self.item('ROW-1', 12)])

    def item(self, name, qty, item='ITEM', warehouse='WH', factor=1):
        return frappe._dict(name=name, idx=1, item_code=item, item_name=item,
                            warehouse=warehouse, qty=qty, stock_qty=qty * factor,
                            stock_uom='PCS', uom='BOX' if factor != 1 else 'PCS', conversion_factor=factor)

    def rule(self, name, location, capacity, priority, **extra):
        return frappe._dict(name=name, warehouse='WH', location=location,
                            stock_capacity=capacity, stock_uom='PCS', priority=priority, **extra)

    def plan(self, doc, rules, physical=None, reserved=None):
        with (patch.object(wrr, 'get_ordered_dimension_putaway_rules', return_value=(False, rules)),
              patch.object(wrr, 'get_physical_quantities', return_value=physical or {}),
              patch.object(wrr, 'get_reserved_quantities', return_value=reserved or {}),
              patch.object(wrr, 'get_location', side_effect=lambda name: frappe._dict(name=name, disabled=0, is_group=0, custom_warehouse='WH', custom_restricted_item=''))):
            return wrr.plan_allocations(doc)['WH']

    def test_priority_and_capacity_split_without_changing_bulk(self):
        doc = self.doc()
        rules = [self.rule('R2', 'B', 20, 2), self.rule('R1', 'A', 10, 1)]
        rows = self.plan(doc, rules, physical={('ITEM', 'A', 'PCS'): 7})
        self.assertEqual([(r['suggested_location'], r['suggested_qty']) for r in rows], [('A', 3), ('B', 9)])
        self.assertEqual(len(doc.get('items')), 1)
        self.assertEqual(doc.get('items')[0].qty, 12)

    def test_full_locations_skipped_and_remainder_retained(self):
        rows = self.plan(self.doc(), [self.rule('R1', 'A', 10, 1), self.rule('R2', 'B', 5, 2)],
                         physical={('ITEM', 'A', 'PCS'): 10})
        self.assertEqual([(r['suggested_location'], r['suggested_qty']) for r in rows], [('B', 5), ('', 7)])
        self.assertEqual(rows[-1]['status'], 'UNALLOCATED')

    def test_repeated_rows_share_space_and_keep_source_identity(self):
        doc = self.doc([self.item('ROW-1', 8), self.item('ROW-2', 8)])
        rows = self.plan(doc, [self.rule('R1', 'A', 10, 1)])
        self.assertEqual([r['suggested_qty'] for r in rows], [8, 2, 6])
        self.assertEqual([r['source_row'] for r in rows], ['ROW-1', 'ROW-2', 'ROW-2'])

    def test_wildcard_capacity_is_shared_between_items(self):
        doc = self.doc([self.item('ROW-1', 8), self.item('ROW-2', 8, item='OTHER')])
        rows = self.plan(doc, [self.rule('R1', 'A', 10, 1, custom_no_item_restriction=1)])
        self.assertEqual([r['suggested_qty'] for r in rows], [8, 2, 6])

    def test_other_drafts_reserve_capacity_and_stock_uom_is_used(self):
        doc = self.doc([self.item('ROW-1', 2, factor=10)])
        rows = self.plan(doc, [self.rule('R1', 'A', 30, 1)], reserved={('ITEM', 'A', 'PCS'): 15})
        self.assertEqual([r['suggested_qty'] for r in rows], [15, 5])
        self.assertEqual(doc.get('items')[0].qty, 2)

    def test_missing_rule_preserves_entire_unallocated_quantity(self):
        rows = self.plan(self.doc(), [])
        self.assertEqual(rows[0]['suggested_qty'], 12)
        self.assertEqual(rows[0]['status'], 'UNALLOCATED')

    def test_unlimited_rule_allocates_all_quantity(self):
        rows = self.plan(self.doc(), [self.rule('R1', 'A', 0, 1, custom_no_capacity_restriction=1)])
        self.assertEqual([(r['suggested_location'], r['suggested_qty']) for r in rows], [('A', 12)])

    def test_mixed_units_do_not_consume_wildcard_capacity_as_same_unit(self):
        rows = self.plan(self.doc(), [self.rule('R1', 'A', 10, 1, custom_no_item_restriction=1)],
                         physical={('OTHER', 'A', 'KG'): 3})
        self.assertEqual(rows[0]['status'], 'UNALLOCATED')


def run_tests():
    suite = unittest.defaultTestLoader.loadTestsFromModule(__import__(__name__, fromlist=['']))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise AssertionError('WRR allocation tests failed')
    return {'tests_run': result.testsRun, 'successful': True}


class TestWRRAllocationLifecycle(unittest.TestCase):
    def doc(self):
        return frappe._dict(name='WRR-TEST', company='COMPANY', posting_date='2026-11-09',
                            posting_time='12:00:00', is_return=0, apply_putaway_rule=1, custom_wrr_allocation_enabled=1,
                            items=[frappe._dict(name='ROW', item_code='ITEM', stock_uom='PCS', warehouse='WH', qty=12, conversion_factor=1)])

    def test_receive_blocks_unallocated_before_writing_documents(self):
        row = dict(source_row='ROW', item_code='ITEM', stock_uom='PCS', suggested_qty=12,
                   status='UNALLOCATED', suggested_location='')
        with (patch.object(wrr, 'lock_warehouses'), patch.object(wrr, 'plan_allocations', return_value={'WH': [row]}),
              patch.object(wrr, 'linked_allocations', return_value=[]), patch.object(frappe, 'get_doc') as get_doc):
            with self.assertRaises(frappe.ValidationError):
                wrr.sync_allocations(self.doc(), require_complete=True)
        get_doc.assert_not_called()

    def test_repeated_save_updates_same_allocation(self):
        from unittest.mock import Mock
        allocation = Mock(docstatus=0, warehouse='WH', name='WA-EXISTING')
        row = dict(source_row='ROW', item_code='ITEM', stock_uom='PCS', suggested_qty=12,
                   original_qty=12, status='PENDING_VERIFICATION', suggested_location='A')
        with (patch.object(wrr, 'lock_warehouses'), patch.object(wrr, 'plan_allocations', return_value={'WH': [row]}),
              patch.object(wrr, 'linked_allocations', return_value=[allocation])):
            wrr.sync_allocations(self.doc())
            wrr.sync_allocations(self.doc())
        self.assertEqual(allocation.save.call_count, 2)
        self.assertEqual(allocation.insert.call_count, 0)

    def test_linked_allocation_rejects_direct_mutation(self):
        from qcmc_logic.qcmc_logics.doctype.warehouse_allocation.warehouse_allocation import WarehouseAllocation
        allocation = frappe.get_doc(dict(doctype='Storage Allocation', purchase_receipt='WRR-TEST'))
        with self.assertRaises(frappe.ValidationError):
            WarehouseAllocation.validate(allocation)

    def test_bulk_receipt_checkbox_rpc_does_not_split_items(self):
        from qcmc_logic.overrides.putaway_rule_dimension import apply_dimension_putaway_rule
        items = [dict(doctype='Purchase Receipt Item', name='ROW', item_code='ITEM', qty=12, stock_qty=12)]
        with patch('qcmc_logic.overrides.putaway_rule_dimension.get_ordered_dimension_putaway_rules') as rules:
            result = apply_dimension_putaway_rule('Purchase Receipt', items, 'COMPANY', sync=True)
        self.assertEqual(result, items)
        rules.assert_not_called()


class TestWRRScannerCapacity(unittest.TestCase):
    def test_scanner_combines_physical_wrr_stock_and_draft_reservations(self):
        from qcmc_logic.api.warehouse_allocation import _committed_location_quantities
        with (patch('qcmc_logic.warehouse_capacity.get_physical_quantities', return_value={('ITEM', 'A', 'PCS'): 40}),
              patch('qcmc_logic.warehouse_capacity.get_reserved_quantities', return_value={('ITEM', 'A', 'PCS'): 7, ('OTHER', 'A', 'PCS'): 4})):
            self.assertEqual(_committed_location_quantities('ITEM', 'WH'), {'A': 47})


class TestWRRReviewRegressions(unittest.TestCase):
    def test_native_cancellation_and_trash_hooks_are_preserved(self):
        from qcmc_logic.overrides.purchase_receipt import CustomPurchaseReceipt, PurchaseReceipt
        doc = frappe.get_doc(dict(doctype='Purchase Receipt', items=[]))
        with (patch('qcmc_logic.warehouse_capacity.lock_warehouses'),
              patch.object(PurchaseReceipt, 'before_cancel') as before_cancel):
            CustomPurchaseReceipt.before_cancel(doc)
        before_cancel.assert_called_once()
        with (patch.object(wrr, 'delete_draft_allocations'), patch.object(PurchaseReceipt, 'on_trash') as on_trash):
            CustomPurchaseReceipt.on_trash(doc)
        on_trash.assert_called_once()

    def test_non_stock_return_charge_needs_no_physical_allocation(self):
        doc = frappe._dict(name='RETURN', return_against='WRR', items=[
            frappe._dict(name='CHARGE', item_code='FREIGHT', warehouse='WH', qty=-5, conversion_factor=1)])
        doc.get_stock_items = lambda: []
        with (patch.object(frappe.db, 'sql', return_value=[]), patch.object(wrr, 'linked_allocations', return_value=[]),
              patch.object(wrr, 'get_physical_quantities', return_value={})):
            self.assertEqual(wrr.plan_return_allocations(doc), {})

    def test_scanner_item_rule_skips_space_reserved_by_wrr(self):
        from qcmc_logic.api import stock_entry_scanner as scanner
        row = frappe._dict(name='ROW', item_code='ITEM', item_name='Item', s_warehouse='WIP',
                           t_warehouse='WH', qty=5, transfer_qty=5, conversion_factor=1, stock_uom='PCS', uom='PCS')
        rules = [frappe._dict(name='R1', location='A', warehouse='WH', stock_capacity=10, free_space=10, priority=1),
                 frappe._dict(name='R2', location='B', warehouse='WH', stock_capacity=10, free_space=10, priority=2)]
        def location(name, **kwargs):
            return frappe._dict(name=name, custom_warehouse='WH', inventory_location_id=name,
                                inventory_location_code=name, inventory_location_name=name, parent_storage_location='')
        with (patch.object(scanner, 'get_ordered_dimension_putaway_rules', return_value=(False, rules)),
              patch.object(scanner, '_resolve_storage_location', side_effect=location),
              patch('qcmc_logic.warehouse_capacity.get_physical_quantities', return_value={}),
              patch('qcmc_logic.warehouse_capacity.get_reserved_quantities', return_value={('ITEM', 'A', 'PCS'): 10}),
              patch.object(frappe.db, 'get_value', return_value=frappe._dict(has_batch_no=0, has_serial_no=0))):
            result = scanner._putaway_allocations(frappe._dict(name='STE', company='COMPANY'), row)
        self.assertEqual([(r['inventory_location_id'], r['stock_quantity']) for r in result], [('B', 5)])


class TestWRRReservationQuery(unittest.TestCase):
    def test_draft_return_cannot_offset_inbound_draft_reservation(self):
        import uuid
        from qcmc_logic.warehouse_capacity import get_reserved_quantities
        warehouse = '_WRR_TEST_' + uuid.uuid4().hex
        frappe.db.savepoint('test_wrr_reservation')
        try:
            # Minimal SQL fixtures isolate the reservation query from document
            # validation. No warehouse, receipt, stock or accounting is posted.
            for quantity in (10, -5):
                parent = frappe.get_doc(dict(doctype='Storage Allocation', name=uuid.uuid4().hex,
                                             warehouse=warehouse, status='Draft', docstatus=0))
                parent.db_insert()
                row = frappe.get_doc(dict(doctype='Warehouse Allocation Location', name=uuid.uuid4().hex,
                    parent=parent.name, parenttype='Storage Allocation', parentfield='locations',
                    item_code='TEST-ITEM', stock_uom='PCS', suggested_location='TEST-LOCATION',
                    suggested_qty=quantity, actual_qty=0, status='PENDING_VERIFICATION'))
                row.db_insert()
            self.assertEqual(get_reserved_quantities(warehouse)[('TEST-ITEM', 'TEST-LOCATION', 'PCS')], 10)
        finally:
            frappe.db.rollback(save_point='test_wrr_reservation')


class TestWRRCurrentCapacity(unittest.TestCase):
    def test_scanner_shared_rule_uses_current_stock_instead_of_stale_free_space(self):
        from qcmc_logic.api import stock_entry_scanner as scanner
        row = frappe._dict(name='ROW', item_code='ITEM', item_name='Item', s_warehouse='WIP',
                           t_warehouse='WH', qty=5, transfer_qty=5, conversion_factor=1, stock_uom='PCS', uom='PCS')
        rules = [frappe._dict(name='R1', location='A', warehouse='WH', stock_capacity=10, free_space=10, priority=1, custom_no_item_restriction=1),
                 frappe._dict(name='R2', location='B', warehouse='WH', stock_capacity=10, free_space=10, priority=2, custom_no_item_restriction=1)]
        def location(name, **kwargs):
            return frappe._dict(name=name, custom_warehouse='WH', inventory_location_id=name,
                                inventory_location_code=name, inventory_location_name=name, parent_storage_location='')
        with (patch.object(scanner, 'get_ordered_dimension_putaway_rules', return_value=(False, rules)),
              patch.object(scanner, '_resolve_storage_location', side_effect=location),
              patch('qcmc_logic.warehouse_capacity.get_physical_quantities', return_value={('OTHER', 'A', 'PCS'): 10}),
              patch('qcmc_logic.warehouse_capacity.get_reserved_quantities', return_value={}),
              patch.object(frappe.db, 'get_value', return_value=frappe._dict(has_batch_no=0, has_serial_no=0))):
            result = scanner._putaway_allocations(frappe._dict(name='STE', company='COMPANY'), row)
        self.assertEqual([(r['inventory_location_id'], r['stock_quantity']) for r in result], [('B', 5)])


class TestWRRTransferCapacity(unittest.TestCase):
    def test_location_transfer_counts_receipt_stock_once(self):
        from decimal import Decimal
        from qcmc_logic.api import location_transfer as transfer
        item = frappe._dict(name='ITEM', stock_uom='PCS')
        target = frappe._dict(name='TARGET', custom_restricted_item='')
        rule = frappe._dict(stock_capacity=10, custom_no_capacity_restriction=0, custom_no_item_restriction=1)
        with (patch.object(transfer, '_putaway_rule_for_location', return_value='RULE'),
              patch.object(transfer, 'get_available_dimension_putaway_capacity', return_value=9),
              patch.object(transfer, '_committed_location_quantities', return_value={'TARGET': 5}),
              patch('qcmc_logic.warehouse_capacity.get_committed_totals', return_value={'TARGET': 5}),
              patch.object(frappe, 'get_cached_doc', return_value=rule)):
            transfer._destination_capacity(item, 'COMPANY', 'WH', target, Decimal('5'))


class TestWRRManualPutawaySwitch(unittest.TestCase):
    def doc(self, checked):
        return frappe._dict(name='WRR', docstatus=0, is_return=0, apply_putaway_rule=checked,
            company='COMPANY', posting_date='2026-11-09', posting_time='12:00:00',
            items=[frappe._dict(name='ROW', item_code='ITEM', warehouse='WH', qty=12, conversion_factor=1)])

    def test_saving_preserves_the_users_checkbox_value(self):
        for checked in (0, 1):
            with self.subTest(checked=checked):
                doc = self.doc(checked)
                wrr.prepare_receipt(doc)
                self.assertEqual(doc.apply_putaway_rule, checked)

    def test_unchecked_does_not_generate_putaway_allocations(self):
        doc = self.doc(0)
        wrr.prepare_receipt(doc)
        with (patch.object(wrr, 'linked_allocations', return_value=[]),
              patch.object(wrr, 'lock_warehouses'), patch.object(wrr, 'plan_allocations') as plan):
            self.assertEqual(wrr.sync_allocations(doc, require_complete=True), [])
        plan.assert_not_called()

    def test_unchecking_and_saving_releases_existing_draft_reservation(self):
        from unittest.mock import Mock
        doc = self.doc(0)
        wrr.prepare_receipt(doc)
        allocation = Mock(name='WA', warehouse='WH', docstatus=0)
        with (patch.object(wrr, 'linked_allocations', return_value=[allocation]),
              patch.object(wrr, 'lock_warehouses'), patch.object(wrr, 'plan_allocations') as plan):
            wrr.sync_allocations(doc)
        plan.assert_not_called()
        self.assertEqual(allocation.status, 'Cancelled')
        allocation.set.assert_any_call('locations', [])
        allocation.save.assert_called_once()



class TestWRRNativeAllocationTable(unittest.TestCase):
    def test_native_grid_rows_come_from_linked_allocations(self):
        from types import SimpleNamespace
        doc = SimpleNamespace(name='WRR', is_new=lambda: False,
            get=lambda field: {'custom_wrr_allocation_enabled': 1, 'apply_putaway_rule': 1}.get(field))
        data = [dict(name='WA-1', warehouse='WH', rows=[dict(allocation_row='SOURCE-ROW',
            source_row='ITEM-ROW', item_code='ITEM', location='LOC', quantity=50000,
            stock_uom='PCS', priority=2, putaway_rule='PUT-1', status='VERIFIED')])]
        with patch.object(wrr, 'get_wrr_allocations', return_value=data):
            rows = wrr.get_allocation_grid_rows(doc)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['name'], 'SOURCE-ROW')
        self.assertEqual(rows[0]['warehouse_allocation'], 'WA-1')
        self.assertEqual(rows[0]['location'], 'LOC')
        self.assertEqual(rows[0]['stock_quantity'], 50000)
        self.assertEqual(rows[0]['status'], 'Allocated')

    def test_new_and_unchecked_receipts_have_no_grid_rows(self):
        from types import SimpleNamespace
        for is_new, checked in ((True, 1), (False, 0)):
            doc = SimpleNamespace(name='WRR', is_new=lambda: is_new,
                get=lambda field: {'custom_wrr_allocation_enabled': 1, 'apply_putaway_rule': checked}.get(field))
            with patch.object(wrr, 'get_wrr_allocations') as read:
                self.assertEqual(wrr.get_allocation_grid_rows(doc), [])
            read.assert_not_called()
