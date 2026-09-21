import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.custom.doctype.property_setter.property_setter import make_property_setter


def execute():
	create_custom_fields({
		"Putaway Rule": [
			{
				"fieldname": "custom_no_capacity_restriction",
				"label": "No Capacity Restriction",
				"fieldtype": "Check",
				"insert_after": "custom_no_item_restriction",
				"description": "Allow this Storage Location rule to accept unlimited quantity.",
			},
		],
	}, update=True)

	make_property_setter("Putaway Rule", "capacity", "reqd", 0, "Check")
	make_property_setter(
		"Putaway Rule",
		"capacity",
		"depends_on",
		"eval:!doc.custom_no_capacity_restriction",
		"Data",
	)
	make_property_setter(
		"Putaway Rule",
		"capacity",
		"mandatory_depends_on",
		"eval:!doc.custom_no_capacity_restriction",
		"Data",
	)
	for fieldname in ("uom", "conversion_factor", "stock_uom", "stock_capacity"):
		make_property_setter(
			"Putaway Rule",
			fieldname,
			"depends_on",
			"eval:!doc.custom_no_capacity_restriction && !doc.custom_no_item_restriction",
			"Data",
		)

	frappe.clear_cache(doctype="Putaway Rule")
