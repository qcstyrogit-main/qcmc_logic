"""Retain ERPNext's aligned header/row columns on list refresh and navigation."""
import frappe


def execute():
    if frappe.db.exists('Client Script', 'MR ID'):
        script = frappe.get_doc('Client Script', 'MR ID')
        if script.enabled and 'move_id_column_left' in (script.script or ''):
            script.enabled = 0
            script.save(ignore_permissions=True)
    frappe.clear_cache(doctype='Material Request')
