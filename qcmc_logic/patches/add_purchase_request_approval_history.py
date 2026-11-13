"""Track approvers and recover only approvals demonstrated by Version records."""
import json

import frappe
from qcmc_logic.customs.purchase_request_history import FIELD, approved_users, is_approval

FIELDS = [dict(fieldname=FIELD, label='Previous PR Approvers', fieldtype='Long Text',
               hidden=1, read_only=1, no_copy=1, insert_after='custom_pr_evaluated_on')]


def preserve_list_settings(script):
    old = "frappe.listview_settings['Material Request'] = {"
    if old not in script:
        return script
    # The existing MR ID Form script replaces the entire list settings object.
    # Keep its refresh handler while retaining our onload and ERPNext settings.
    return script.replace(old, "frappe.listview_settings['Material Request'] = Object.assign(frappe.listview_settings['Material Request'] || {}, {", 1).replace('};', '});', 1)


def execute():
    from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

    create_custom_fields({'Material Request': FIELDS})
    recovered = {}
    for version in frappe.get_all('Version', filters={'ref_doctype': 'Material Request'},
                                  fields=['docname', 'owner', 'data'], order_by='creation'):
        try:
            changes = json.loads(version.data).get('changed', [])
        except (ValueError, TypeError, AttributeError):
            continue
        if any(change[0] == 'material_request_type' for change in changes):
            continue
        if any(len(change) == 3 and change[0] == 'workflow_state' and is_approval(change[1], change[2]) for change in changes):
            recovered.setdefault(version.docname, set()).add(version.owner)
    updated = 0
    for name, users in recovered.items():
        row = frappe.db.get_value('Material Request', name, ['material_request_type', FIELD], as_dict=True)
        if not row or row.material_request_type != 'Purchase':
            continue
        old = approved_users(row.get(FIELD))
        combined = sorted(set(old) | users)
        if set(combined) != set(old):
            frappe.db.set_value('Material Request', name, FIELD, json.dumps(combined), update_modified=False)
            frappe.clear_document_cache('Material Request', name)
            updated += 1
    if frappe.db.exists('Client Script', 'MR ID'):
        script = frappe.db.get_value('Client Script', 'MR ID', 'script') or ''
        corrected = preserve_list_settings(script)
        if corrected != script:
            frappe.db.set_value('Client Script', 'MR ID', 'script', corrected)
    frappe.clear_cache()
    return updated
