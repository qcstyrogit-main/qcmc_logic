"""Restore ERPNext item summaries without changing business workflow state."""
import frappe

PLACEHOLDER = '{material_request_type}'


def execute():
    from frappe.custom.doctype.property_setter.property_setter import make_property_setter

    make_property_setter('Material Request', 'title', 'default', '', 'Data')
    rows = frappe.db.sql(
        'SELECT name, material_request_type FROM `tabMaterial Request` WHERE title = %s',
        (PLACEHOLDER,), as_dict=True,
    )
    for row in rows:
        items = frappe.get_all('Material Request Item', filters={'parent': row.name, 'parenttype': 'Material Request'},
                               fields=['item_name', 'item_code'], order_by='idx', limit_page_length=3)
        summary = ', '.join(item.item_name or item.item_code or '' for item in items)
        title = frappe._('{0} Request for {1}').format(frappe._(row.material_request_type), summary)[:100]
        frappe.db.sql('UPDATE `tabMaterial Request` SET title=%s WHERE name=%s AND title=%s',
                      (title, row.name, PLACEHOLDER))
        frappe.clear_document_cache('Material Request', row.name)
    frappe.clear_cache(doctype='Material Request')
    return len(rows)
