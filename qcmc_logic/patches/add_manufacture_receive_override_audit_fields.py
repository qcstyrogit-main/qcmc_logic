import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	create_custom_fields({
		"Stock Entry Detail": [
			{"fieldname": "custom_putaway_allocation_id", "label": "Putaway Allocation ID", "fieldtype": "Data", "read_only": 1, "hidden": 1, "no_copy": 1},
			{"fieldname": "custom_recommended_storage_location", "label": "Recommended Storage Location", "fieldtype": "Link", "options": "Storage Location", "read_only": 1, "no_copy": 1},
			{"fieldname": "custom_actual_storage_location", "label": "Actual Storage Location", "fieldtype": "Link", "options": "Storage Location", "read_only": 1, "no_copy": 1},
			{"fieldname": "custom_location_overridden", "label": "Location Overridden", "fieldtype": "Check", "read_only": 1, "no_copy": 1},
			{"fieldname": "custom_location_override_device", "label": "Location Override Device", "fieldtype": "Data", "read_only": 1, "no_copy": 1},
			{"fieldname": "custom_location_override_timestamp", "label": "Location Override Timestamp", "fieldtype": "Datetime", "read_only": 1, "no_copy": 1},
		],
	}, update=True)
