import json

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	create_custom_fields(
		{
			"Sales Order Item": [
				{
					"fieldname": "custom_next_scheduling_date",
					"label": "Next Scheduling Date",
					"fieldtype": "Date",
					"insert_after": "delivery_date",
					"read_only": 1,
					"allow_on_submit": 1,
					"description": "Earliest date a released balance returns to Delivery Scheduling.",
				}
			],
		},
		update=True,
	)
	_backfill_stock_confirmation_removals()
	frappe.clear_cache(doctype="Sales Order Item")


def _backfill_stock_confirmation_removals():
	comments = frappe.get_all(
		"Comment",
		filters={
			"reference_doctype": "Delivery Note",
			"comment_type": "Edit",
			"content": ["like", "Stock Confirmation: %Removed unavailable item%"],
		},
		fields=["reference_name", "creation"],
	)
	for comment in comments:
		versions = frappe.get_all(
			"Version",
			filters={
				"ref_doctype": "Delivery Note",
				"docname": comment.reference_name,
				"creation": ["<=", comment.creation],
			},
			fields=["creation", "data"],
			order_by="creation desc",
			limit=1,
		)
		if not versions:
			continue
		if abs(frappe.utils.time_diff_in_seconds(comment.creation, versions[0].creation)) > 60:
			continue
		try:
			removed = json.loads(versions[0].data or "{}").get("removed", [])
		except (TypeError, ValueError):
			continue
		for table_field, row in removed:
			if table_field != "items" or not row.get("so_detail"):
				continue
			delivery_date = frappe.db.get_value(
				"Sales Order Item", row["so_detail"], "delivery_date"
			)
			if delivery_date:
				frappe.db.set_value(
					"Sales Order Item",
					row["so_detail"],
					"custom_next_scheduling_date",
					frappe.utils.add_days(delivery_date, 1),
					update_modified=False,
				)
