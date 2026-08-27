import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	dimension = frappe.db.get_value(
		"Inventory Dimension",
		{
			"reference_document": "Storage Location",
			"source_fieldname": "location",
		},
		"name",
	)
	if not dimension:
		dimension = frappe.get_doc(
			{
				"doctype": "Inventory Dimension",
				"dimension_name": "Location",
				"reference_document": "Storage Location",
				"apply_to_all_doctypes": 1,
			}
		).insert(ignore_permissions=True).name

	create_custom_fields(
		{
			"Stock Reconciliation Item": [
				{
					"fieldname": "custom_scanned_device",
					"label": "Scanner ID",
					"fieldtype": "Data",
					"insert_after": "location",
					"read_only": 1,
					"in_list_view": 1,
					"description": "ID reported by the scanner that recorded this item",
				},
				{
					"fieldname": "custom_scanned_by",
					"label": "User's Full Name",
					"fieldtype": "Data",
					"insert_after": "custom_scanned_device",
					"read_only": 1,
					"in_list_view": 1,
					"description": "Full name of the authenticated scanner user who recorded this item",
				}
			]
		},
		update=True,
	)

	location_field = "Stock Reconciliation Item-location"
	if frappe.db.exists("Custom Field", location_field):
		frappe.db.set_value(
			"Custom Field",
			location_field,
			{"in_list_view": 1, "label": "Location"},
			update_modified=False,
		)

	if frappe.db.has_column("Stock Reconciliation Item", "storage_location"):
		frappe.db.sql(
			"""
			update `tabStock Reconciliation Item` sri
			inner join `tabStock Reconciliation` sr on sr.name = sri.parent
			set sri.location = sri.storage_location
			where sr.docstatus = 0
			  and coalesce(sri.location, '') = ''
			  and coalesce(sri.storage_location, '') != ''
			"""
		)

	for row in frappe.get_all(
		"Stock Reconciliation Item",
		filters={"custom_scanned_device": ["is", "set"], "custom_scanned_by": ["is", "not set"]},
		fields=["name", "owner"],
	):
		full_name = frappe.get_cached_value("User", row.owner, "full_name") or row.owner
		frappe.db.set_value(
			"Stock Reconciliation Item",
			row.name,
			"custom_scanned_by",
			full_name,
			update_modified=False,
		)

	old_field = "Stock Reconciliation Item-storage_location"
	if frappe.db.exists("Custom Field", old_field):
		frappe.delete_doc("Custom Field", old_field, force=True, ignore_permissions=True)

	frappe.clear_cache(doctype="Stock Reconciliation Item")
