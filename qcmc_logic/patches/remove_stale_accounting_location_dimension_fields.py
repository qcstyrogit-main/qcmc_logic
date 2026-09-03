import frappe


ACCOUNTING_LOCATION_FIELDNAMES = {
	"location",
	"source_location",
	"target_location",
	"accounting_dimensions_section",
	"dimension_col_break",
}


def execute():
	affected_doctypes = set()

	for field in frappe.get_all(
		"Custom Field",
		filters={
			"fieldname": ["in", tuple(ACCOUNTING_LOCATION_FIELDNAMES)],
			"is_system_generated": 1,
		},
		fields=["name", "dt", "options"],
	):
		if field.options and field.options != "Location":
			continue
		affected_doctypes.add(field.dt)
		frappe.delete_doc(
			"Custom Field",
			field.name,
			ignore_permissions=True,
			force=True,
		)

	for setter in frappe.get_all(
		"Property Setter",
		filters={
			"field_name": ["in", tuple(ACCOUNTING_LOCATION_FIELDNAMES)],
			"doctype_or_field": "DocField",
			"is_system_generated": 1,
		},
		fields=["name", "doc_type", "field_name"],
	):
		if setter.doc_type == "Asset" and setter.field_name == "location":
			continue
		affected_doctypes.add(setter.doc_type)
		frappe.delete_doc(
			"Property Setter",
			setter.name,
			ignore_permissions=True,
			force=True,
		)

	for doctype in affected_doctypes:
		frappe.clear_cache(doctype=doctype)

	frappe.clear_cache(doctype="Accounting Dimension")
