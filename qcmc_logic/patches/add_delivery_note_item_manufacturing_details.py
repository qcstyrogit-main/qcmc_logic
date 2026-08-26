import json

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


DOCTYPE = "Delivery Note Item"
FIELDS = [
	{
		"fieldname": "custom_manufacturing_details_section",
		"label": "Manufacturing Details",
		"fieldtype": "Section Break",
		"insert_after": "batch_no",
	},
	{
		"fieldname": "custom_manufacture_date",
		"label": "Manufacture Date",
		"fieldtype": "Date",
		"insert_after": "custom_manufacturing_details_section",
	},
	{
		"fieldname": "custom_lot_number",
		"label": "Lot Number",
		"fieldtype": "Data",
		"insert_after": "custom_manufacture_date",
	},
	{
		"fieldname": "custom_quantity",
		"label": "Quantity",
		"fieldtype": "Float",
		"insert_after": "custom_lot_number",
	},
]


def execute():
	create_custom_fields({DOCTYPE: FIELDS}, update=True)
	_sync_field_order_property_setter()
	frappe.clear_cache(doctype=DOCTYPE)


def _sync_field_order_property_setter():
	setter_name = frappe.db.get_value(
		"Property Setter",
		{"doc_type": DOCTYPE, "property": "field_order"},
		"name",
	)
	if not setter_name:
		return

	value = frappe.db.get_value("Property Setter", setter_name, "value")
	try:
		field_order = json.loads(value)
	except (TypeError, ValueError):
		return

	custom_fieldnames = [field["fieldname"] for field in FIELDS]
	field_order = [fieldname for fieldname in field_order if fieldname not in custom_fieldnames]
	anchor_index = field_order.index("available_qty_section") if "available_qty_section" in field_order else len(field_order)
	field_order[anchor_index:anchor_index] = custom_fieldnames

	frappe.db.set_value(
		"Property Setter",
		setter_name,
		"value",
		json.dumps(field_order),
		update_modified=False,
	)
