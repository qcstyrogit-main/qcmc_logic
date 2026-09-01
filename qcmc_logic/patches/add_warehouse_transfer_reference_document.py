import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


FIELDNAME = "custom_reference_document"
DOCTYPE = "Warehouse Transfer"


def execute():
	if not frappe.db.exists("DocType", DOCTYPE):
		return

	create_custom_fields(
		{
			DOCTYPE: [
				{
					"fieldname": FIELDNAME,
					"label": "Reference Document",
					"fieldtype": "Data",
					"insert_after": "transfer_type",
					"in_list_view": 1,
					"allow_on_submit": 1,
				},
			],
		},
		update=True,
	)
	frappe.clear_cache(doctype=DOCTYPE)
