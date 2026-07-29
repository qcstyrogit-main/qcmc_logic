import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


CHILD_DOCTYPE = "EPS Work Order Sales Order Item"


def execute():
	create_child_doctype()
	create_custom_fields(
		{
			"Work Order": [
				{
					"fieldname": "custom_eps_sales_order_items_section",
					"label": "EPS Sales Order Items",
					"fieldtype": "Section Break",
					"insert_after": "sales_order_item",
					"collapsible": 1,
				},
				{
					"fieldname": "custom_eps_sales_order_items",
					"label": "Secondary Output Sales Order Items",
					"fieldtype": "Table",
					"options": CHILD_DOCTYPE,
					"insert_after": "custom_eps_sales_order_items_section",
				},
			]
		},
		ignore_validate=True,
	)
	frappe.clear_cache(doctype="Work Order")


def create_child_doctype():
	if frappe.db.exists("DocType", CHILD_DOCTYPE):
		return

	doc = frappe.get_doc(
		{
			"doctype": "DocType",
			"name": CHILD_DOCTYPE,
			"module": "QCMC Logics",
			"custom": 1,
			"istable": 1,
			"editable_grid": 1,
			"field_order": [
				"item_code",
				"item_name",
				"type",
				"qty",
				"stock_uom",
				"sales_order",
				"sales_order_item",
				"customer_name",
				"delivery_date",
				"bom_secondary_item",
			],
			"fields": [
				{
					"fieldname": "item_code",
					"label": "Item Code",
					"fieldtype": "Link",
					"options": "Item",
					"in_list_view": 1,
					"reqd": 1,
				},
				{
					"fieldname": "item_name",
					"label": "Item Name",
					"fieldtype": "Data",
					"read_only": 1,
					"in_list_view": 1,
				},
				{
					"fieldname": "type",
					"label": "Type",
					"fieldtype": "Select",
					"options": "Co-Product\nBy-Product\nScrap\nAdditional Finished Good",
					"default": "Co-Product",
					"in_list_view": 1,
				},
				{
					"fieldname": "qty",
					"label": "Qty",
					"fieldtype": "Float",
					"in_list_view": 1,
					"reqd": 1,
				},
				{
					"fieldname": "stock_uom",
					"label": "Stock UOM",
					"fieldtype": "Link",
					"options": "UOM",
					"read_only": 1,
				},
				{
					"fieldname": "sales_order",
					"label": "Sales Order",
					"fieldtype": "Link",
					"options": "Sales Order",
					"in_list_view": 1,
					"reqd": 1,
				},
				{
					"fieldname": "sales_order_item",
					"label": "Sales Order Item",
					"fieldtype": "Link",
					"options": "Sales Order Item",
					"in_list_view": 1,
					"reqd": 1,
				},
				{
					"fieldname": "customer_name",
					"label": "Customer",
					"fieldtype": "Data",
					"read_only": 1,
				},
				{
					"fieldname": "delivery_date",
					"label": "Delivery Date",
					"fieldtype": "Date",
					"read_only": 1,
				},
				{
					"fieldname": "bom_secondary_item",
					"label": "BOM Secondary Item",
					"fieldtype": "Data",
					"hidden": 1,
					"read_only": 1,
				},
			],
		}
	)
	doc.insert(ignore_permissions=True)
