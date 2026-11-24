"""Persist the existing Logistics Reason Code choice on each SO schedule."""

from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	create_custom_fields({"SO Delivery Schedule": [
		{"fieldname": "logistics_reason", "label": "Logistics Reason", "fieldtype": "Data",
			"insert_after": "logistics_committed_qty"},
	]}, update=True)
