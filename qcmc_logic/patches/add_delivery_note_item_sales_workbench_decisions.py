import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	create_custom_fields(
		{
			"Delivery Note Item": [
				{
					"fieldname": "custom_sales_final_qty",
					"label": "Sales Final DR Qty",
					"fieldtype": "Float",
					"insert_after": "custom_logistics_proposed_date",
				},
				{
					"fieldname": "custom_sales_move_date",
					"label": "Sales Move Date",
					"fieldtype": "Date",
					"insert_after": "custom_sales_final_qty",
				},
				{
					"fieldname": "custom_sales_remove",
					"label": "Sales Remove",
					"fieldtype": "Check",
					"insert_after": "custom_sales_move_date",
				},
			]
		},
		update=True,
	)
	frappe.clear_cache(doctype="Delivery Note Item")
