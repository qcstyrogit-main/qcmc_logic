import json

import frappe


LEGACY_FIELDNAMES = {
	"inventory_dimension",
	"inventory_dimension_col_break",
	"bin",
	"rack",
	"room",
	"aisle",
	"bldg",
	"to_bin",
	"to_rack",
	"to_room",
	"to_aisle",
	"to_bldg",
	"from_bin",
	"from_rack",
	"from_room",
	"from_aisle",
	"from_bldg",
	"rejected_bin",
	"rejected_rack",
	"rejected_room",
	"rejected_aisle",
	"rejected_bldg",
}

LEGACY_SECTION_FIELDNAMES = {
	"inventory_dimension",
	"inventory_dimension_col_break",
}

ACCOUNTING_DIMENSION_SECTION_FIELDNAMES = {
	"accounting_dimensions_section",
	"dimension_col_break",
}

LEGACY_ACCOUNTING_DIMENSION_FIELDNAMES = {
	"location",
	"source_location",
	"target_location",
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
	"User",
	"Warranty Claim",
	"Warehouse Transfer",
	"Warehouse Transfer Details",
}


def execute():
	deleted_mismatched_custom_fields = remove_mismatched_custom_fields()
	deleted_custom_fields = remove_legacy_custom_fields()
	deleted_accounting_dimension_fields = remove_stale_accounting_dimension_fields()
	updated_property_setters = clean_field_order_property_setters()
	deleted_property_setters = remove_stale_dimension_property_setters()

	for doctype in LEGACY_DOCTYPES:
		frappe.clear_cache(doctype=doctype)

	frappe.clear_cache(doctype="Inventory Dimension")
	frappe.clear_cache(doctype="Accounting Dimension")

	return {
		"deleted_mismatched_custom_fields": deleted_mismatched_custom_fields,
		"deleted_custom_fields": deleted_custom_fields,
		"deleted_accounting_dimension_fields": deleted_accounting_dimension_fields,
		"updated_property_setters": updated_property_setters,
		"deleted_property_setters": deleted_property_setters,
	}


def remove_mismatched_custom_fields():
	fields = frappe.get_all(
		"Custom Field",
		fields=["name", "dt", "fieldname"],
	)

	deleted = 0
	affected_doctypes = set()
	for field in fields:
		if field.name != f"{field.dt}-{field.fieldname}":
			affected_doctypes.add(field.dt)
			frappe.delete_doc("Custom Field", field.name, ignore_permissions=True, force=True)
			deleted += 1

	for doctype in affected_doctypes:
		frappe.clear_cache(doctype=doctype)

	return deleted


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


def remove_stale_accounting_dimension_fields():
	active_fieldnames = get_active_accounting_dimension_fieldnames()
	target_fieldnames = get_stale_accounting_dimension_fieldnames(active_fieldnames)

	if not target_fieldnames:
		return 0

	fields = frappe.get_all(
		"Custom Field",
		filters={
			"fieldname": ("in", tuple(target_fieldnames)),
			"is_system_generated": 1,
		},
		fields=["name"],
	)

	deleted = 0
	for field in fields:
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


def get_active_accounting_dimension_fieldnames():
	return {
		dimension.fieldname
		for dimension in frappe.get_all(
			"Accounting Dimension",
			filters={"disabled": 0},
			fields=["fieldname"],
		)
		if dimension.fieldname
	}


def get_stale_accounting_dimension_fieldnames(active_fieldnames):
	stale_fieldnames = LEGACY_ACCOUNTING_DIMENSION_FIELDNAMES - active_fieldnames

	if not active_fieldnames:
		stale_fieldnames |= ACCOUNTING_DIMENSION_SECTION_FIELDNAMES

	return stale_fieldnames


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
	stale_fieldnames = get_stale_dimension_fieldnames()
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

		cleaned_field_order = [field for field in field_order if field not in stale_fieldnames]
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


def remove_stale_dimension_property_setters():
	stale_fieldnames = get_stale_dimension_fieldnames()
	property_setters = frappe.get_all(
		"Property Setter",
		filters={
			"field_name": ("in", tuple(stale_fieldnames)),
			"doctype_or_field": "DocField",
		},
		fields=["name"],
	)

	deleted = 0
	for setter in property_setters:
		frappe.delete_doc("Property Setter", setter.name, ignore_permissions=True, force=True)
		deleted += 1

	return deleted


def get_stale_dimension_fieldnames():
	active_inventory_fieldnames = get_active_inventory_dimension_fieldnames()
	active_accounting_fieldnames = get_active_accounting_dimension_fieldnames()
	stale_inventory_fieldnames = {
		fieldname
		for fieldname in LEGACY_FIELDNAMES
		if is_stale_inventory_dimension_field(
			frappe._dict(fieldname=fieldname), active_inventory_fieldnames
		)
	}

	return stale_inventory_fieldnames | get_stale_accounting_dimension_fieldnames(
		active_accounting_fieldnames
	)
