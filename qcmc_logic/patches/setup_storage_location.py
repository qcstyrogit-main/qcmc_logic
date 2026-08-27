import frappe
from frappe.custom.doctype.property_setter.property_setter import make_property_setter


def execute():
	section = "Stock Reconciliation Item-inventory_dimension"
	if frappe.db.exists("Custom Field", section):
		frappe.db.set_value("Custom Field", section, "label", "Physical Location", update_modified=False)

	make_property_setter("Stock Reconciliation", "set_warehouse", "reqd", 1, "Check")

	frappe.clear_cache(doctype="Stock Reconciliation Item")
