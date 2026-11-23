import frappe

from qcmc_logic.api import delivery_printing_service as delivery_note_printing


@frappe.whitelist()
def get_data(filters=None):
	return delivery_note_printing.get_workbench_data(filters)


@frappe.whitelist(methods=["POST"])
def assign_dr_number(delivery_note, dr_number):
	return delivery_note_printing.assign_dr_number(delivery_note, dr_number)


@frappe.whitelist(methods=["POST"])
def create_sales_invoices(delivery_notes, invoice_number):
	return delivery_note_printing.create_sales_invoices(delivery_notes, invoice_number)


@frappe.whitelist(methods=["POST"])
def verify_sales_invoice_for_preview(delivery_note, sales_invoice=None, invoice_number=None):
	return delivery_note_printing.verify_sales_invoice_for_preview(
		delivery_note=delivery_note,
		invoice_number=invoice_number,
		sales_invoice=sales_invoice,
	)


@frappe.whitelist()
def submit_for_delivery(delivery_notes):
	return delivery_note_printing.submit_for_delivery(delivery_notes)
