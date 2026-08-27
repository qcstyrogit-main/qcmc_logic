import frappe
from frappe.custom.doctype.property_setter.property_setter import make_property_setter


def execute():
	make_property_setter("Stock Reconciliation", "set_warehouse", "reqd", 1, "Check")
	frappe.clear_cache(doctype="Stock Reconciliation")
	frappe.clear_cache(doctype="Stock Reconciliation Item")
