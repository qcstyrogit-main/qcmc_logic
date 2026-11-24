"""Add fields required for Logistics-confirmed schedule transfers."""

from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	create_custom_fields({"SO Delivery Schedule": [
		{"fieldname": "logistics_transfer_qty", "label": "Logistics Transfer Qty", "fieldtype": "Float", "insert_after": "logistics_remarks", "non_negative": 1},
		{"fieldname": "logistics_destination_date", "label": "Logistics Destination Date", "fieldtype": "Date", "insert_after": "logistics_transfer_qty"},
		{"fieldname": "source_schedule", "label": "From Schedule", "fieldtype": "Link", "options": "SO Delivery Schedule", "insert_after": "original_promise_qty", "read_only": 1, "search_index": 1},
		{"fieldname": "source_date", "label": "From Date", "fieldtype": "Date", "insert_after": "source_schedule", "read_only": 1},
		{"fieldname": "movement_transaction_id", "label": "Movement Transaction ID", "fieldtype": "Data", "insert_after": "source_date", "read_only": 1, "search_index": 1},
	]}, update=True)
