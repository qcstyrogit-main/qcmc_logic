"""Rename the allocation parent DocType without changing allocation identifiers."""
import json

import frappe
from frappe.model.rename_doc import rename_doc

OLD_NAME = 'Warehouse Allocation'
NEW_NAME = 'Storage Allocation'


def execute():
    old_exists = frappe.db.exists('DocType', OLD_NAME)
    new_exists = frappe.db.exists('DocType', NEW_NAME)
    if old_exists and new_exists:
        frappe.throw('Both Warehouse Allocation and Storage Allocation exist. Refusing to merge allocation records.')
    if not old_exists:
        if new_exists:
            update_workspace_references()
            frappe.clear_cache()
        return
    previous = frappe.flags.in_patch
    frappe.flags.in_patch = True
    try:
        rename_doc('DocType', OLD_NAME, NEW_NAME, force=True,
                          ignore_permissions=True, show_alert=False, rebuild_search=False)
    finally:
        frappe.flags.in_patch = previous
    update_workspace_references()
    frappe.clear_cache()


def _rename_content(value):
    if isinstance(value, list):
        return [_rename_content(item) for item in value]
    if isinstance(value, dict):
        return {key: _rename_content(item) for key, item in value.items()}
    if value == OLD_NAME:
        return NEW_NAME
    if isinstance(value, str):
        old_route = '/app/warehouse-allocation'
        if value == old_route or value.startswith(old_route + '/') or value.startswith(old_route + '?'):
            return '/app/storage-allocation' + value[len(old_route):]
    return value


def update_workspace_references():
    # Labels and block content are plain text rather than DocType Link fields,
    # so the framework's automatic link migration cannot update them.
    frappe.db.set_value('Custom Field', {
        'dt': 'Purchase Receipt',
        'fieldname': ['in', ['custom_warehouse_allocation_section', 'custom_warehouse_allocation']],
        'label': OLD_NAME,
    }, 'label', NEW_NAME, update_modified=False)
    for doctype in ('Workspace Shortcut', 'Workspace Link'):
        if not frappe.db.table_exists(doctype):
            continue
        for field in ('label', 'link_to'):
            if frappe.db.has_column(doctype, field):
                frappe.db.set_value(doctype, {field: OLD_NAME}, field, NEW_NAME, update_modified=False)
    for row in frappe.get_all('Workspace', fields=['name', 'content']):
        if not row.content:
            continue
        try:
            content = json.loads(row.content)
        except (ValueError, TypeError):
            continue
        renamed = _rename_content(content)
        if renamed != content:
            frappe.db.set_value('Workspace', row.name, 'content', json.dumps(renamed), update_modified=False)
