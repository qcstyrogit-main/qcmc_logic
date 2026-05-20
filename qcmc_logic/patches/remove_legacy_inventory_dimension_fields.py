import json

import frappe


LEGACY_FIELDNAMES = {
	"inventory_dimension",
	"inventory_dimension_col_break",
	"bin",
	"rack",
	"room",
	"aisle",
	"to_bin",
	"to_rack",
	"to_room",
	"to_aisle",
	"from_bin",
	"from_rack",
	"from_room",
	"from_aisle",
	"rejected_bin",
	"rejected_rack",
	"rejected_room",
	"rejected_aisle",
}

LEGACY_SECTION_FIELDNAMES = {
	"inventory_dimension",
	"inventory_dimension_col_break",
}

LEGACY_DOCTYPES = {
	"Asset Capitalization",
	"Asset Capitalization Stock Item",
	"Delivery Note Item",
	"Job Card",
	"Maintenance Visit Purpose",
	"POS Invoice Item",
	"Packed Item",
	"Packing Slip Item",
	"Purchase Invoice Item",
	"Purchase Receipt Item",
	"Purchase Receipt Item Supplied",
	"Putaway Rule",
	"Quality Inspection",
	"Sales Invoice Item",
	"Stock Entry Detail",
	"Stock Reconciliation Item",
	"Subcontracting Receipt Item",
	"Subcontracting Receipt Supplied Item",
	"Warranty Claim",
}


def execute():
	deleted_custom_fields = remove_legacy_custom_fields()
	updated_property_setters = clean_field_order_property_setters()

	for doctype in LEGACY_DOCTYPES:
		frappe.clear_cache(doctype=doctype)

	frappe.clear_cache(doctype="Inventory Dimension")

	return {
		"deleted_custom_fields": deleted_custom_fields,
		"updated_property_setters": updated_property_setters,
	}


def remove_legacy_custom_fields():
	fields = frappe.get_all(
		"Custom Field",
		filters={
			"dt": ("in", tuple(LEGACY_DOCTYPES)),
			"fieldname": ("in", tuple(LEGACY_FIELDNAMES)),
		},
		fields=["name", "fieldname", "options", "is_system_generated"],
	)

	deleted = 0
	for field in fields:
		if is_legacy_inventory_dimension_field(field):
			frappe.delete_doc("Custom Field", field.name, ignore_permissions=True, force=True)
			deleted += 1

	return deleted


def is_legacy_inventory_dimension_field(field):
	if not field.is_system_generated:
		return False

	if field.fieldname in LEGACY_SECTION_FIELDNAMES:
		return True

	return field.options == "Bin"


def clean_field_order_property_setters():
	updated_property_setters = 0
	property_setters = frappe.get_all(
		"Property Setter",
		filters={
			"doc_type": ("in", tuple(LEGACY_DOCTYPES)),
			"property": "field_order",
		},
		fields=["name", "value"],
	)

	for setter in property_setters:
		try:
			field_order = json.loads(setter.value)
		except (TypeError, ValueError):
			continue

		if not isinstance(field_order, list):
			continue

		cleaned_field_order = [field for field in field_order if field not in LEGACY_FIELDNAMES]
		if cleaned_field_order != field_order:
			updated_property_setters += 1
			frappe.db.set_value(
				"Property Setter",
				setter.name,
				"value",
				json.dumps(cleaned_field_order),
				update_modified=False,
			)

	return updated_property_setters
