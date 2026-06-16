import frappe


def execute():
    if frappe.db.exists("DocType", "Warehouse Transfer Details"):
        doc = frappe.get_doc("DocType", "Warehouse Transfer Details")
    else:
        doc = frappe.new_doc("DocType")
        doc.name = "Warehouse Transfer Details"

    doc.module = "Stock"
    doc.custom = 1
    doc.allow_rename = 1
    doc.editable_grid = 1
    doc.istable = 1
    doc.title_field = ""
    doc.sort_field = "creation"
    doc.rows_threshold_for_grid_search = 0
    doc.permissions = []
    doc.fields = []

    for field in _warehouse_transfer_detail_fields():
        doc.append("fields", field)

    if doc.is_new():
        doc.insert(ignore_permissions=True)
    else:
        doc.save(ignore_permissions=True)

    frappe.clear_cache(doctype="Warehouse Transfer Details")


def _warehouse_transfer_detail_fields():
    return [
        {
            "fieldname": "item_code",
            "label": "Item",
            "fieldtype": "Link",
            "options": "Item",
            "in_list_view": 1,
        },
        {
            "fieldname": "item_name",
            "label": "Item Name",
            "fieldtype": "Data",
            "fetch_from": "item_code.item_name",
            "in_list_view": 1,
        },
        {
            "fieldname": "uom",
            "label": "UOM",
            "fieldtype": "Data",
            "options": "UOM",
            "fetch_from": "item_code.default_bom",
            "in_list_view": 1,
        },
        {
            "fieldname": "issued_qty",
            "label": "Issued Qty",
            "fieldtype": "Float",
            "in_list_view": 1,
        },
        {
            "fieldname": "received_qty",
            "label": "Received Qty",
            "fieldtype": "Float",
            "allow_on_submit": 1,
            "in_list_view": 1,
        },
        {
            "fieldname": "reference_doc",
            "label": "Remarks",
            "fieldtype": "Data",
            "in_list_view": 1,
        },
        {
            "fieldname": "material_request",
            "label": "Material Request",
            "fieldtype": "Link",
            "options": "Material Request",
            "hidden": 1,
            "read_only": 1,
            "no_copy": 1,
            "print_hide": 1,
        },
        {
            "fieldname": "material_request_item",
            "label": "Material Request Item",
            "fieldtype": "Data",
            "hidden": 1,
            "read_only": 1,
            "no_copy": 1,
            "print_hide": 1,
        },
    ]
