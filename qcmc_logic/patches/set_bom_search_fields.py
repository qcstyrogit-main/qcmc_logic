import frappe
from frappe.custom.doctype.property_setter.property_setter import make_property_setter


SEARCH_FIELDS = "item,item_name,custom_machine,routing"


def execute():
	make_property_setter(
		"BOM",
		None,
		"search_fields",
		SEARCH_FIELDS,
		"Data",
		for_doctype=True,
	)
	frappe.db.set_value("DocType", "BOM", "search_fields", SEARCH_FIELDS, update_modified=False)
	frappe.clear_cache(doctype="BOM")
