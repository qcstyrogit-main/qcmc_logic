import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
    frappe.reload_doc('qcmc_logics','doctype','storage_allocation')
    create_custom_fields({'Delivery Note': [
        dict(fieldname='custom_apply_putaway_rule',label='Apply Putaway Rule',fieldtype='Check',
             default='0',insert_after='is_return',depends_on='eval:doc.is_return',
             description='Save to reserve return storage by priority and available capacity. Submit requires full allocation.'),
        dict(fieldname='custom_storage_allocation_enabled',label='Use Storage Allocation',fieldtype='Check',
             hidden=1,read_only=1,no_copy=1,insert_after='custom_apply_putaway_rule'),
        dict(fieldname='custom_storage_allocation_section',label='Storage Allocation',fieldtype='Section Break',
             insert_after='items',depends_on='eval:!doc.__islocal && doc.is_return && doc.custom_storage_allocation_enabled && doc.custom_apply_putaway_rule'),
        dict(fieldname='custom_storage_allocation',label='Storage Allocation',fieldtype='Table',
             options='WRR Allocation Detail',is_virtual=1,read_only=1,no_copy=1,
             insert_after='custom_storage_allocation_section'),
    ]},update=True)
    frappe.db.add_unique('Storage Allocation',['delivery_note','warehouse'],'unique_dn_warehouse')
    frappe.clear_cache(doctype='Delivery Note')
