"""Remove redundant metadata; keep the native field and its stored values."""
import frappe


def execute():
    native = frappe.db.get_value('DocField',
                                 {'parent': 'Purchase Invoice VAT Detail', 'fieldname': 'cost_center'},
                                 ['fieldtype', 'options'], as_dict=True)
    if not native or native.fieldtype != 'Link' or native.options != 'Cost Center':
        return
    # Avoid Custom Field on_trash: its property-setter cleanup also targets the
    # surviving native field. This removes only duplicate metadata, never columns.
    frappe.db.delete('Custom Field', {'dt': 'Purchase Invoice VAT Detail', 'fieldname': 'cost_center'})
    frappe.clear_cache(doctype='Purchase Invoice VAT Detail')
