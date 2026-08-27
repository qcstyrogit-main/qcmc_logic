import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	create_custom_fields(
		{
			"Vehicle": [
				{"fieldname": "custom_gps_tracking_section", "label": "GPS Tracking", "fieldtype": "Section Break", "insert_after": "location"},
				{"fieldname": "custom_gps_tracking_enabled", "label": "GPS Tracking Enabled", "fieldtype": "Check", "default": "0", "insert_after": "custom_gps_tracking_section"},
				{"fieldname": "custom_gps_provider", "label": "GPS Provider", "fieldtype": "Select", "options": "\nAIKA", "insert_after": "custom_gps_tracking_enabled"},
				{"fieldname": "custom_aika_tracker", "label": "AIKA Account", "fieldtype": "Link", "options": "AIKA GPS Tracker", "insert_after": "custom_gps_provider"},
				{"fieldname": "custom_gps_device_id", "label": "AIKA Internal Device ID", "fieldtype": "Data", "unique": 1, "read_only": 1, "insert_after": "custom_aika_tracker"},
				{"fieldname": "custom_gps_id_number", "label": "GPS ID Number", "fieldtype": "Data", "unique": 1, "read_only": 0, "insert_after": "custom_gps_device_id"},
				{"fieldname": "custom_gps_device_name", "label": "GPS Device Name", "fieldtype": "Data", "read_only": 1, "insert_after": "custom_gps_id_number"},
				{"fieldname": "custom_gps_last_position", "label": "GPS Last Position", "fieldtype": "Datetime", "read_only": 1, "insert_after": "custom_gps_device_name"},
				{"fieldname": "custom_gps_latitude", "label": "GPS Latitude", "fieldtype": "Float", "precision": "7", "read_only": 1, "insert_after": "custom_gps_last_position"},
				{"fieldname": "custom_gps_longitude", "label": "GPS Longitude", "fieldtype": "Float", "precision": "7", "read_only": 1, "insert_after": "custom_gps_latitude"},
				{"fieldname": "custom_gps_speed_kph", "label": "GPS Speed (km/h)", "fieldtype": "Float", "read_only": 1, "insert_after": "custom_gps_longitude"},
			]
		},
		update=True,
	)
