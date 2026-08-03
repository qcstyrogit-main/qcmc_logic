import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


PWT_SHIPPING_DEPENDS_ON = (
    "eval:doc.transfer_type == 'Provincial Warehouse Transfer' "
    "&& doc.custom_with_shipping_details"
)
PWT_DEPENDS_ON = "eval:doc.transfer_type == 'Provincial Warehouse Transfer'"
SHIPPING_FIELDS = (
    "custom_shipping_details_section",
    "custom_etd",
    "custom_eta",
    "custom_shipping_details_column_break",
    "custom_seal_no",
    "custom_van_no",
    "custom_shipping_line",
    "custom_shipping_remarks",
)


def execute():
    create_custom_fields(
        {
            "Warehouse Transfer": [
                {
                    "fieldname": "custom_shipping_details_section",
                    "label": "Shipping Details",
                    "fieldtype": "Section Break",
                    "insert_after": "transfer_items",
                    "collapsible": 1,
                },
                {
                    "fieldname": "custom_with_shipping_details",
                    "label": "With Shipping Details",
                    "fieldtype": "Check",
                    "insert_after": "transfer_type",
                    "depends_on": PWT_DEPENDS_ON,
                },
                {
                    "fieldname": "custom_etd",
                    "label": "ETD",
                    "fieldtype": "Datetime",
                    "insert_after": "custom_shipping_details_section",
                    "depends_on": PWT_SHIPPING_DEPENDS_ON,
                },
                {
                    "fieldname": "custom_eta",
                    "label": "ETA",
                    "fieldtype": "Datetime",
                    "insert_after": "custom_etd",
                    "depends_on": PWT_SHIPPING_DEPENDS_ON,
                },
                {
                    "fieldname": "custom_shipping_details_column_break",
                    "fieldtype": "Column Break",
                    "insert_after": "custom_eta",
                    "depends_on": PWT_SHIPPING_DEPENDS_ON,
                },
                {
                    "fieldname": "custom_seal_no",
                    "label": "Seal No",
                    "fieldtype": "Data",
                    "insert_after": "custom_shipping_details_column_break",
                    "depends_on": PWT_SHIPPING_DEPENDS_ON,
                },
                {
                    "fieldname": "custom_van_no",
                    "label": "Van No",
                    "fieldtype": "Data",
                    "insert_after": "custom_seal_no",
                    "depends_on": PWT_SHIPPING_DEPENDS_ON,
                },
                {
                    "fieldname": "custom_shipping_line",
                    "label": "Shipping Line",
                    "fieldtype": "Link",
                    "options": "Supplier",
                    "insert_after": "custom_van_no",
                    "depends_on": PWT_SHIPPING_DEPENDS_ON,
                },
                {
                    "fieldname": "custom_shipping_remarks",
                    "label": "Shipping Remarks",
                    "fieldtype": "Small Text",
                    "insert_after": "custom_shipping_line",
                    "depends_on": PWT_SHIPPING_DEPENDS_ON,
                },
            ]
        },
        ignore_validate=True,
    )

    update_shipping_line_supplier_link()
    update_shipping_details_layout()
    make_shipping_fields_allow_on_submit()
    frappe.clear_cache(doctype="Warehouse Transfer")


def update_shipping_line_supplier_link():
    fieldname = "Warehouse Transfer-custom_shipping_line"
    if not frappe.db.exists("Custom Field", fieldname):
        return

    frappe.db.set_value(
        "Custom Field",
        fieldname,
        {
            "fieldtype": "Link",
            "options": "Supplier",
        },
        update_modified=False,
    )


def update_shipping_details_layout():
    updates = {
        "Warehouse Transfer-custom_with_shipping_details": {
            "insert_after": "transfer_type",
            "depends_on": PWT_DEPENDS_ON,
        },
        "Warehouse Transfer-custom_shipping_details_section": {
            "insert_after": "transfer_items",
            "depends_on": None,
        },
        "Warehouse Transfer-custom_etd": {
            "insert_after": "custom_shipping_details_section",
            "depends_on": PWT_SHIPPING_DEPENDS_ON,
        },
    }

    for fieldname, values in updates.items():
        if frappe.db.exists("Custom Field", fieldname):
            frappe.db.set_value("Custom Field", fieldname, values, update_modified=False)


def make_shipping_fields_allow_on_submit():
    for fieldname in SHIPPING_FIELDS:
        name = f"Warehouse Transfer-{fieldname}"
        if frappe.db.exists("Custom Field", name):
            frappe.db.set_value(
                "Custom Field",
                name,
                {
                    "allow_on_submit": 1,
                    "depends_on": None
                    if fieldname == "custom_shipping_details_section"
                    else PWT_SHIPPING_DEPENDS_ON,
                },
                update_modified=False,
            )
