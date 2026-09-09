import frappe
from frappe.contacts.doctype.address.address import get_company_address
from frappe.model.mapper import get_mapped_doc
from frappe.model.utils import get_fetch_values
from frappe.utils import cint, today

from erpnext.accounts.party import get_due_date


@frappe.whitelist()
def create_sales_invoice_from_draft_dn(dn_name):
	def set_missing_values(source, target):
		# Match the initialization performed by ERPNext's Sales Order and
		# submitted Delivery Note invoice mappers.
		target.posting_date = today()
		target.run_method("set_missing_values")
		target.run_method("set_po_nos")
		target.run_method("calculate_taxes_and_totals")
		target.run_method("set_use_serial_batch_fields")

		if source.company_address:
			target.company_address = source.company_address
		else:
			target.update(get_company_address(target.company))

		if target.company_address:
			target.update(get_fetch_values("Sales Invoice", "company_address", target.company_address))

	def update_item(source, target, source_parent):
		target.qty = source.qty
		target._old_name = source.name

	sales_invoice = get_mapped_doc(
		"Delivery Note",
		dn_name,
		{
			"Delivery Note": {
				"doctype": "Sales Invoice",
				"field_map": {
					"is_return": "is_return",
					"custom_dr_number": "custom_delivery_number",
				},
			},
			"Delivery Note Item": {
				"doctype": "Sales Invoice Item",
				"field_map": {
					"name": "dn_detail",
					"parent": "delivery_note",
					"so_detail": "so_detail",
					"against_sales_order": "sales_order",
					"cost_center": "cost_center",
				},
				"postprocess": update_item,
			},
			"Sales Taxes and Charges": {
				"doctype": "Sales Taxes and Charges",
				"reset_value": True,
			},
			"Sales Team": {
				"doctype": "Sales Team",
				"field_map": {"incentives": "incentives"},
				"add_if_empty": True,
			},
		},
		postprocess=set_missing_values,
	)

	if cint(frappe.get_single_value("Accounts Settings", "automatically_fetch_payment_terms")):
		sales_invoice.set_payment_schedule()
	else:
		_set_payment_terms_from_sales_order(sales_invoice)

	return sales_invoice


def _set_payment_terms_from_sales_order(sales_invoice):
	sales_order, doctype, fieldname = sales_invoice.get_order_details()
	if not sales_invoice.linked_order_has_payment_terms(sales_order, fieldname, doctype):
		return

	sales_invoice.payment_terms_template = frappe.db.get_value(
		doctype, sales_order, "payment_terms_template"
	)
	sales_invoice.due_date = get_due_date(
		sales_invoice.posting_date,
		"Customer",
		sales_invoice.customer,
		sales_invoice.company,
		template_name=sales_invoice.payment_terms_template,
	)
