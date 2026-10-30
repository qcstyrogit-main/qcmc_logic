import frappe
from frappe.contacts.doctype.address.address import get_company_address
from frappe.model.mapper import get_mapped_doc
from frappe.model.utils import get_fetch_values
from frappe.utils import cint, today

from erpnext.accounts.party import get_due_date

SALES_ORDER_PRICING_FIELDS = (
	"rate",
	"base_rate",
	"price_list_rate",
	"base_price_list_rate",
	"discount_percentage",
	"discount_amount",
	"margin_type",
	"margin_rate_or_amount",
)


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
		apply_sales_order_item_pricing(source, target)

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


@frappe.whitelist()
def get_delivery_note_draft_invoices(dn_name):
	doc = frappe.get_doc("Delivery Note", dn_name)
	doc.check_permission("read")
	if doc.docstatus != 0 or doc.workflow_state != "To Deliver and Bill":
		return []
	rows = frappe.db.sql("""
		SELECT DISTINCT si.name, si.docstatus
		FROM `tabSales Invoice Item` sii JOIN `tabSales Invoice` si ON si.name = sii.parent
		WHERE sii.delivery_note = %s AND si.docstatus < 2
		ORDER BY si.creation
	""", dn_name, as_dict=True)
	return [
		{"name": row.name, "docstatus": row.docstatus,
		 "can_write": frappe.has_permission("Sales Invoice", "write", doc=row.name)}
		for row in rows if frappe.has_permission("Sales Invoice", "read", doc=row.name)
	]


@frappe.whitelist()
def sync_draft_invoice_quantities_from_delivery_note(dn_name):
	doc = frappe.get_doc("Delivery Note", dn_name)
	doc.check_permission("write")
	if doc.docstatus != 0 or doc.workflow_state != "To Deliver and Bill":
		frappe.throw(frappe._("Only a draft Delivery Note in To Deliver and Bill can update linked draft invoices."))
	for item in doc.items:
		from qcmc_logic.qcmc_logics.report.delivery_note_printing import delivery_note_printing
		delivery_note_printing._validate_warehouse_access(item.warehouse, require_transact=True)
	rows = frappe.db.sql("""
		SELECT DISTINCT si.name, si.docstatus
		FROM `tabSales Invoice Item` sii JOIN `tabSales Invoice` si ON si.name = sii.parent
		WHERE sii.delivery_note = %s AND si.docstatus < 2
	""", dn_name, as_dict=True)
	if any(row.docstatus == 1 for row in rows):
		frappe.throw(frappe._("A linked invoice has already been submitted. Correct the invoice through the approved amendment process."))
	qty_by_detail = {item.name: item.qty for item in doc.items}
	updated = []
	for row in rows:
		invoice = frappe.get_doc("Sales Invoice", row.name)
		invoice.check_permission("write")
		changed = False
		for item in invoice.items:
			if item.delivery_note == dn_name and item.dn_detail in qty_by_detail and item.qty != qty_by_detail[item.dn_detail]:
				item.qty = qty_by_detail[item.dn_detail]
				changed = True
		if changed:
			invoice.run_method("calculate_taxes_and_totals")
			invoice.save()
			updated.append(invoice.name)
	return updated


def apply_sales_order_item_pricing(source_doc, target_doc):
	so_detail = source_doc.get("so_detail")
	if not so_detail:
		return

	sales_order_item = frappe.get_doc("Sales Order Item", so_detail)
	for fieldname in SALES_ORDER_PRICING_FIELDS:
		set_value = getattr(target_doc, "set", None)
		if callable(set_value):
			set_value(fieldname, sales_order_item.get(fieldname))
		else:
			target_doc[fieldname] = sales_order_item.get(fieldname)


def apply_sales_order_pricing_to_invoice(sales_invoice):
	for item in sales_invoice.get("items") or []:
		apply_sales_order_item_pricing(item, item)
	sales_invoice.run_method("calculate_taxes_and_totals")


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
