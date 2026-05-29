import json

import frappe
from frappe.custom.doctype.property_setter.property_setter import make_property_setter


TRANSACTION_DOCTYPES = (
	"Delivery Note",
	"Journal Entry",
	"Material Request",
	"Payment Entry",
	"POS Invoice",
	"Purchase Invoice",
	"Purchase Order",
	"Purchase Receipt",
	"Quotation",
	"Request for Quotation",
	"Sales Invoice",
	"Sales Order",
	"Supplier Quotation",
)


def execute():
	for doctype in TRANSACTION_DOCTYPES:
		remove_title_from_field_order(doctype)
		hide_title_field(doctype)
		frappe.clear_cache(doctype=doctype)

	remove_title_from_list_view()


def remove_title_from_field_order(doctype):
	setter_name = f"{doctype}-main-field_order"
	value = frappe.db.get_value("Property Setter", setter_name, "value")
	if not value:
		return

	try:
		field_order = json.loads(value)
	except (TypeError, ValueError):
		return

	if not isinstance(field_order, list) or "title" not in field_order:
		return

	field_order = [field for field in field_order if field != "title"]
	frappe.db.set_value(
		"Property Setter",
		setter_name,
		"value",
		json.dumps(field_order),
		update_modified=False,
	)


def hide_title_field(doctype):
	setter_name = f"{doctype}-title-hidden"
	if frappe.db.exists("Property Setter", setter_name):
		frappe.db.set_value(
			"Property Setter",
			setter_name,
			"value",
			"1",
			update_modified=False,
		)
		return

	if frappe.db.exists("DocField", {"parent": doctype, "fieldname": "title"}):
		make_property_setter(doctype, "title", "hidden", "1", "Check")


def remove_title_from_list_view():
	setters = frappe.get_all(
		"Property Setter",
		filters={
			"doc_type": ("in", TRANSACTION_DOCTYPES),
			"field_name": "title",
			"property": "in_list_view",
		},
		pluck="name",
	)

	for setter in setters:
		frappe.delete_doc("Property Setter", setter, ignore_permissions=True, force=True)
