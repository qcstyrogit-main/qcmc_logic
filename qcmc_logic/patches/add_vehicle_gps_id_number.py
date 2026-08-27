import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	create_custom_fields(
		{"Vehicle": [
			{"fieldname": "custom_gps_device_id", "label": "AIKA Internal Device ID", "fieldtype": "Data", "unique": 1, "read_only": 1, "insert_after": "custom_aika_tracker"},
			{"fieldname": "custom_gps_id_number", "label": "GPS ID Number", "fieldtype": "Data", "unique": 1, "read_only": 0, "insert_after": "custom_gps_device_id"},
			{"fieldname": "custom_gps_device_name", "label": "GPS Device Name", "fieldtype": "Data", "read_only": 1, "insert_after": "custom_gps_id_number"},
		]},
		update=True,
	)
