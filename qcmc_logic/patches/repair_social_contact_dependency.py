"""Repair the optional chat child table before User saves load Contacts."""

from pathlib import Path

import frappe


def execute():
    if frappe.db.exists('DocType', 'Social Contact'):
        frappe.clear_cache(doctype='Social Contact')
        frappe.clear_cache(doctype='Contact')
        return {'action': 'already_available'}

    if 'clefincode_chat' in frappe.get_installed_apps():
        source = Path(frappe.get_app_path(
            'clefincode_chat', 'clefincode_chat', 'doctype', 'social_contact', 'social_contact.json'
        ))
        if source.is_file():
            # Restore the owner's actual schema rather than inventing a copy.
            frappe.reload_doc('clefincode_chat', 'doctype', 'social_contact', force=True)
            frappe.clear_cache(doctype='Social Contact')
            frappe.clear_cache(doctype='Contact')
            return {'action': 'restored'}

    field = frappe.db.exists('Custom Field', {
        'dt': 'Contact', 'fieldname': 'social_contact',
        'fieldtype': 'Table', 'options': 'Social Contact',
    })
    if not field:
        return {'action': 'nothing_to_repair'}

    # Only remove orphaned form metadata. Do not drop tables or contact data.
    frappe.delete_doc('Custom Field', field, ignore_permissions=True, force=True)
    frappe.clear_cache(doctype='Contact')
    return {'action': 'removed_orphan_field'}
