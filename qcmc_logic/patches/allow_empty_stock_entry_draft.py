import frappe
from frappe.custom.doctype.property_setter.property_setter import make_property_setter


def execute():
	# Submission safety is enforced by CustomStockEntry.validate. Removing the
	# metadata-level requirement lets the form save an empty header as Draft.
	make_property_setter("Stock Entry", "items", "reqd", 0, "Check")
	frappe.clear_cache(doctype="Stock Entry")
