import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_field


def execute():
	if not frappe.db.exists("DocType", "Stock Settings"):
		return

	if frappe.get_meta("Stock Settings").has_field("custom_default_actual_weight_uom"):
		clear_actual_weight_uom_item_fetch()
		frappe.clear_cache(doctype="Stock Settings")
		frappe.clear_cache(doctype="Stock Entry Detail")
		return

	create_custom_field(
		"Stock Settings",
		{
			"fieldname": "custom_default_actual_weight_uom",
			"label": "Default Actual Weight UOM",
			"fieldtype": "Link",
			"options": "UOM",
			"insert_after": "custom_restrict_source_target_warehouse_type",
			"description": (
				"Default UOM applied to Actual Wt/Item on finished item rows in "
				"Manufacture Stock Entries."
			),
		},
		ignore_validate=True,
	)
	clear_actual_weight_uom_item_fetch()

	frappe.clear_cache(doctype="Stock Settings")
	frappe.clear_cache(doctype="Stock Entry Detail")


def clear_actual_weight_uom_item_fetch():
	field_name = "Stock Entry Detail-custom_actual_weight_uom"
	if not frappe.db.exists("Custom Field", field_name):
		return

	frappe.db.set_value(
		"Custom Field",
		field_name,
		{
			"fetch_from": None,
			"fetch_if_empty": 0,
		},
	)
