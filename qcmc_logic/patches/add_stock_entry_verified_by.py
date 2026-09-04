import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	if frappe.get_meta("Stock Entry").has_field("custom_verified_by"):
		return

	create_custom_fields(
		{
			"Stock Entry": [{
				"fieldname": "custom_verified_by",
				"label": "Verified By",
				"fieldtype": "Link",
				"options": "Assign Checker",
				"insert_after": "custom_reference_document",
				"read_only": 1,
				"allow_on_submit": 0,
				"in_standard_filter": 1,
			}],
		},
		ignore_validate=True,
	)
	frappe.clear_cache(doctype="Stock Entry")
