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
	"Stock Closing Balance",
	"Stock Entry Detail",
	"Stock Ledger Entry",
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
	active_fieldnames = get_active_inventory_dimension_fieldnames()
	fields = frappe.get_all(
		"Custom Field",
		filters={
			"fieldname": ("in", tuple(LEGACY_FIELDNAMES)),
			"is_system_generated": 1,
		},
		fields=["name", "dt", "fieldname", "options", "is_system_generated"],
	)

	deleted = 0
	for field in fields:
		if is_stale_inventory_dimension_field(field, active_fieldnames):
			frappe.delete_doc("Custom Field", field.name, ignore_permissions=True, force=True)
			deleted += 1

	return deleted


def get_active_inventory_dimension_fieldnames():
	fieldnames = set()

	for dimension in frappe.get_all(
		"Inventory Dimension",
		fields=["source_fieldname", "target_fieldname"],
	):
		source_fieldname = dimension.source_fieldname
		target_fieldname = dimension.target_fieldname

		for fieldname in {source_fieldname, target_fieldname}:
			if fieldname:
				fieldnames.add(fieldname)

		if source_fieldname:
			fieldnames.update(
				{
					f"to_{source_fieldname}",
					f"from_{source_fieldname}",
					f"rejected_{source_fieldname}",
				}
			)

	return fieldnames


def is_stale_inventory_dimension_field(field, active_fieldnames):
	if field.fieldname in active_fieldnames:
		return False

	if field.fieldname in LEGACY_SECTION_FIELDNAMES:
		return not active_fieldnames

	if field.fieldname in LEGACY_FIELDNAMES:
		return True

	return False


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
