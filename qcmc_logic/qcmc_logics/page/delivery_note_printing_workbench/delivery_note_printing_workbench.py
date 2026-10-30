import frappe
from frappe import _

from qcmc_logic.qcmc_logics.report.delivery_note_printing import delivery_note_printing


@frappe.whitelist()
def get_data(filters=None):
	filters = frappe._dict(frappe.parse_json(filters or "{}"))
	delivery_note_printing._validate_invoicing_role()
	if not filters.get("company") or not filters.get("delivery_date"):
		return {"rows": [], "message": _("Select a company and delivery date.")}
	doc_names = frappe.get_list(
		"Delivery Note",
		filters={"company": filters.company, "docstatus": 0, "workflow_state": "For DR Printing"},
		fields=["name"],
		order_by="modified asc",
		page_length=0,
	)
	rows = []
	for entry in doc_names:
		doc = frappe.get_doc("Delivery Note", entry.name)
		if not frappe.has_permission("Delivery Note", "read", doc=doc):
			continue
		try:
			for item in doc.items:
				delivery_note_printing._validate_warehouse_access(item.warehouse)
		except frappe.PermissionError:
			continue
		items = []
		for item in doc.items:
			items.append({"item_code": item.item_code, "item_name": item.item_name, "qty": item.qty, "warehouse": item.warehouse})
		delivery_note_date = str(doc.posting_date or doc.get("posting_date") or "")
		if not items or not delivery_note_date or delivery_note_date > str(filters.delivery_date):
			continue
		if filters.get("warehouse") and not any(item["warehouse"] == filters.warehouse for item in items):
			continue
		invoice_rows = frappe.db.sql("""
			SELECT DISTINCT si.name, si.docstatus
			FROM `tabSales Invoice Item` sii JOIN `tabSales Invoice` si ON si.name = sii.parent
			WHERE sii.delivery_note = %s AND si.docstatus < 2
			ORDER BY si.creation
		""", doc.name, as_dict=True)
		invoices = [
			{"name": row.name, "status": _( "Draft") if row.docstatus == 0 else _("Submitted")}
			for row in invoice_rows if frappe.has_permission("Sales Invoice", "read", row.name)
		]
		rows.append({
			"delivery_note": doc.name,
			"delivery_note_date": delivery_note_date,
			"dr_number": doc.get("custom_dr_number"),
			"sales_order": doc.get("custom_sales_order") or ", ".join(sorted({item.get("against_sales_order") for item in doc.items if item.get("against_sales_order")})),
			"customer_name": doc.customer_name,
			"item_count": len(items),
			"items": items,
			"invoices": invoices,
			"modified": str(doc.modified),
		})
	return {"rows": rows, "message": _("{0} Delivery Note(s) ready for DR printing.").format(len(rows))}


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
