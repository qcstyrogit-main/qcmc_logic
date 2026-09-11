import frappe
from frappe.custom.doctype.property_setter.property_setter import make_property_setter


def execute():
    make_property_setter(
        'Material Request', None, 'track_changes', 1, 'Check', for_doctype=True
    )
    frappe.clear_cache(doctype='Material Request')
