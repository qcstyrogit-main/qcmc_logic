import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
    create_custom_fields({'Purchase Receipt': [
        dict(fieldname='custom_wrr_allocation_enabled', label='Use Storage Allocation',
             fieldtype='Check', hidden=1, read_only=1, no_copy=1, insert_after='apply_putaway_rule'),
        dict(fieldname='custom_warehouse_allocation_section', label='Storage Allocation',
             fieldtype='Section Break', insert_after='items',
             depends_on='eval:!doc.__islocal && doc.custom_wrr_allocation_enabled'),
        dict(fieldname='custom_warehouse_allocation', label='Storage Allocation',
             fieldtype='Table', options='WRR Allocation Detail', is_virtual=1,
             read_only=1, no_copy=1, insert_after='custom_warehouse_allocation_section'),
    ]}, update=True)
    frappe.db.add_unique('Storage Allocation', ['purchase_receipt', 'warehouse'], 'unique_wrr_warehouse')
    frappe.clear_cache(doctype='Purchase Receipt')
