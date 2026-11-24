"""Make the existing SO Delivery Schedule collaboration fields reproducible."""

from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	create_custom_fields({"SO Delivery Schedule": [
		{"fieldname": "sales_proposed_qty", "label": "Sales Proposed Qty", "fieldtype": "Float", "insert_after": "remarks", "non_negative": 1},
		{"fieldname": "sales_remarks", "label": "Sales Remarks", "fieldtype": "Small Text", "insert_after": "sales_proposed_qty"},
		{"fieldname": "logistics_committed_qty", "label": "Logistics Committed Qty", "fieldtype": "Float", "insert_after": "sales_remarks", "non_negative": 1},
		{"fieldname": "logistics_reason", "label": "Logistics Reason", "fieldtype": "Data", "insert_after": "logistics_committed_qty"},
		{"fieldname": "logistics_remarks", "label": "Logistics Remarks", "fieldtype": "Small Text", "insert_after": "logistics_reason"},
		{"fieldname": "logistics_transfer_qty", "label": "Logistics Transfer Qty", "fieldtype": "Float", "insert_after": "logistics_remarks", "non_negative": 1},
		{"fieldname": "logistics_destination_date", "label": "Logistics Destination Date", "fieldtype": "Date", "insert_after": "logistics_transfer_qty"},
		{"fieldname": "final_qty", "label": "Final Qty", "fieldtype": "Float", "insert_after": "logistics_remarks", "non_negative": 1},
		{"fieldname": "confirmation_status", "label": "Confirmation Status", "fieldtype": "Select", "options": "Pending\nIn Review\nFinalized", "default": "Pending", "insert_after": "final_qty", "in_list_view": 1},
		{"fieldname": "sales_confirmed_by", "label": "Sales Confirmed By", "fieldtype": "Link", "options": "User", "insert_after": "confirmation_status", "read_only": 1},
		{"fieldname": "logistics_confirmed_by", "label": "Logistics Confirmed By", "fieldtype": "Link", "options": "User", "insert_after": "sales_confirmed_by", "read_only": 1},
		{"fieldname": "finalized_at", "label": "Finalized At", "fieldtype": "Datetime", "insert_after": "logistics_confirmed_by", "read_only": 1},
		{"fieldname": "source_schedule", "label": "From Schedule", "fieldtype": "Link", "options": "SO Delivery Schedule", "insert_after": "original_promise_qty", "read_only": 1, "search_index": 1},
		{"fieldname": "source_date", "label": "From Date", "fieldtype": "Date", "insert_after": "source_schedule", "read_only": 1},
		{"fieldname": "movement_transaction_id", "label": "Movement Transaction ID", "fieldtype": "Data", "insert_after": "source_date", "read_only": 1, "search_index": 1},
	]}, update=True)
