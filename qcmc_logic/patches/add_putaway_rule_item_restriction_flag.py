import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.custom.doctype.property_setter.property_setter import make_property_setter


def execute():
	create_custom_fields({
		"Putaway Rule": [
			{
				"fieldname": "custom_no_item_restriction",
				"label": "No Item Restriction",
				"fieldtype": "Check",
				"insert_after": "disable",
				"description": "Allow this rule to accept any Item for the selected Warehouse and Storage Location.",
			},
		],
	}, update=True)

	make_property_setter("Putaway Rule", "item_code", "reqd", 0, "Check")
	make_property_setter(
		"Putaway Rule",
		"item_code",
		"depends_on",
		"eval:!doc.custom_no_item_restriction",
		"Data",
	)
	make_property_setter(
		"Putaway Rule",
		"item_code",
		"mandatory_depends_on",
		"eval:!doc.custom_no_item_restriction",
		"Data",
	)

	frappe.clear_cache(doctype="Putaway Rule")
