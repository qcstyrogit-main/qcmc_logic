import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
    frappe.reload_doc('qcmc_logics','doctype','storage_allocation')
    create_custom_fields({'Warehouse Transfer': [
        dict(fieldname='custom_apply_putaway_rule', label='Apply Putaway Rule', fieldtype='Check',
             default='0', insert_after='target_warehouse', allow_on_submit=1,
             description='Save to reserve storage locations by priority and available capacity. Receive requires full allocation.'),
        dict(fieldname='custom_storage_allocation_enabled',label='Use Storage Allocation',fieldtype='Check',
             hidden=1,read_only=1,no_copy=1,allow_on_submit=1,insert_after='custom_apply_putaway_rule'),
        dict(fieldname='custom_storage_allocation_section',label='Storage Allocation',fieldtype='Section Break',
             insert_after='transfer_items',depends_on='eval:!doc.__islocal && doc.custom_storage_allocation_enabled && doc.custom_apply_putaway_rule'),
        dict(fieldname='custom_storage_allocation',label='Storage Allocation',fieldtype='Table',
             options='WRR Allocation Detail',read_only=1,no_copy=1,allow_on_submit=1,
             insert_after='custom_storage_allocation_section'),
    ], 'Warehouse Transfer Details': [
        # ERPNext's stock reversal clears this field even for non-batched items.
        dict(fieldname='serial_and_batch_bundle',label='Serial and Batch Bundle',
             fieldtype='Link',options='Serial and Batch Bundle',hidden=1,read_only=1,
             allow_on_submit=1,no_copy=1,insert_after='reference_doc'),
    ]},update=True)
    frappe.db.add_unique('Storage Allocation',['warehouse_transfer','warehouse'],'unique_wt_warehouse')
    frappe.clear_cache(doctype='Warehouse Transfer')
