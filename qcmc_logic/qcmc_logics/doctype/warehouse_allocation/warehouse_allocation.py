import json
from collections import defaultdict

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


class WarehouseAllocation(Document):
	pass


SOURCE_DOCTYPES = (
	"Stock Entry",
	"Warehouse Transfer",
	"Purchase Receipt",
	"Delivery Note",
	"Sales Invoice",
)

RECEIVING_STOCK_ENTRY_PURPOSES = (
	"Material Receipt",
	"Material Transfer",
	"Manufacture",
	"Repack",
)


@frappe.whitelist()
def get_receiving_documents(source_doctype, company=None, warehouse=None):
	source_doctype = _validate_source_doctype(source_doctype)
	if source_doctype == "Stock Entry":
		return _get_receiving_stock_entries(company, warehouse)
	if source_doctype == "Warehouse Transfer":
		return _get_receiving_warehouse_transfers(company, warehouse)
	if source_doctype == "Purchase Receipt":
		return _get_purchase_receipts(company, warehouse)
	if source_doctype == "Delivery Note":
		return _get_delivery_note_returns(company, warehouse)
	return _get_sales_invoice_returns(company, warehouse)


@frappe.whitelist()
def get_items_from_documents(source_doctype, documents, company=None, warehouse=None):
	source_doctype = _validate_source_doctype(source_doctype)
	documents = _as_list(documents)
	if not documents:
		frappe.throw(_("Select at least one document."))
	documents = tuple(documents)

	rows = []
	if source_doctype == "Stock Entry":
		rows = _get_stock_entry_rows(documents, company, warehouse)
	elif source_doctype == "Warehouse Transfer":
		rows = _get_warehouse_transfer_rows(documents, company, warehouse)
	elif source_doctype == "Purchase Receipt":
		rows = _get_purchase_receipt_rows(documents, company, warehouse)
	elif source_doctype == "Delivery Note":
		rows = _get_delivery_note_return_rows(documents, company, warehouse)
	else:
		rows = _get_sales_invoice_return_rows(documents, company, warehouse)

	if not rows:
		frappe.throw(_("No receiving item rows were found for the selected documents."))

	return {
		"references": rows,
		"items": _consolidate_items(rows),
	}


def _validate_source_doctype(source_doctype):
	if source_doctype not in SOURCE_DOCTYPES:
		frappe.throw(_("Source document type {0} is not supported.").format(frappe.bold(source_doctype)))
	return source_doctype


def _as_list(value):
	if isinstance(value, str):
		try:
			value = json.loads(value)
		except ValueError:
			value = [value]
	return [item for item in (value or []) if item]


def _company_filter(company):
	return {"company": company} if company else {}


def _warehouse_condition(alias, warehouse):
	return f" and {alias}.warehouse = %(warehouse)s" if warehouse else ""


def _stock_entry_warehouse_condition(warehouse):
	return " and sed.t_warehouse = %(warehouse)s" if warehouse else ""


def _get_receiving_stock_entries(company=None, warehouse=None):
	return frappe.db.sql(
		f"""
		select distinct se.name, se.posting_date, se.company, se.stock_entry_type, se.purpose
		from `tabStock Entry` se
		inner join `tabStock Entry Detail` sed on sed.parent = se.name
		left join `tabStock Entry Type` setype on setype.name = se.stock_entry_type
		where se.docstatus = 1
			and coalesce(setype.purpose, se.purpose) in %(purposes)s
			and sed.t_warehouse is not null
			and sed.t_warehouse != ''
			and sed.qty > 0
			{_stock_entry_warehouse_condition(warehouse)}
			{"and se.company = %(company)s" if company else ""}
		order by se.posting_date desc, se.name desc
		limit 100
		""",
		{"purposes": RECEIVING_STOCK_ENTRY_PURPOSES, "company": company, "warehouse": warehouse},
		as_dict=True,
	)


def _get_purchase_receipts(company=None, warehouse=None):
	return frappe.db.sql(
		f"""
		select distinct pr.name, pr.posting_date, pr.company, pr.supplier
		from `tabPurchase Receipt` pr
		inner join `tabPurchase Receipt Item` pri on pri.parent = pr.name
		where pr.docstatus = 1
			and pri.qty > 0
			{_warehouse_condition("pri", warehouse)}
			{"and pr.company = %(company)s" if company else ""}
		order by pr.posting_date desc, pr.name desc
		limit 100
		""",
		{"company": company, "warehouse": warehouse},
		as_dict=True,
	)


def _get_receiving_warehouse_transfers(company=None, warehouse=None):
	return frappe.db.sql(
		f"""
		select distinct wt.name, wt.date_transferred as posting_date, wt.target_company as company,
			wt.source_warehouse, wt.target_warehouse, wt.transfer_status
		from `tabWarehouse Transfer` wt
		inner join `tabWarehouse Transfer Details` wtd on wtd.parent = wt.name
		where wt.docstatus = 1
			and wt.transfer_status = 'Transferred'
			and coalesce(wtd.issued_qty, 0) > coalesce(wtd.received_qty, 0)
			{"and wt.target_warehouse = %(warehouse)s" if warehouse else ""}
			{"and wt.target_company = %(company)s" if company else ""}
		order by wt.date_transferred desc, wt.name desc
		limit 100
		""",
		{"company": company, "warehouse": warehouse},
		as_dict=True,
	)


def _get_delivery_note_returns(company=None, warehouse=None):
	return frappe.db.sql(
		f"""
		select distinct dn.name, dn.posting_date, dn.company, dn.customer
		from `tabDelivery Note` dn
		inner join `tabDelivery Note Item` dni on dni.parent = dn.name
		where dn.docstatus = 1
			and dn.is_return = 1
			and dni.qty < 0
			{_warehouse_condition("dni", warehouse)}
			{"and dn.company = %(company)s" if company else ""}
		order by dn.posting_date desc, dn.name desc
		limit 100
		""",
		{"company": company, "warehouse": warehouse},
		as_dict=True,
	)


def _get_sales_invoice_returns(company=None, warehouse=None):
	return frappe.db.sql(
		f"""
		select distinct si.name, si.posting_date, si.company, si.customer
		from `tabSales Invoice` si
		inner join `tabSales Invoice Item` sii on sii.parent = si.name
		where si.docstatus = 1
			and si.is_return = 1
			and si.update_stock = 1
			and sii.qty < 0
			{_warehouse_condition("sii", warehouse)}
			{"and si.company = %(company)s" if company else ""}
		order by si.posting_date desc, si.name desc
		limit 100
		""",
		{"company": company, "warehouse": warehouse},
		as_dict=True,
	)


def _get_stock_entry_rows(documents, company=None, warehouse=None):
	return frappe.db.sql(
		f"""
		select se.name as source_name, 'Stock Entry' as source_doctype, sed.item_code,
			sed.qty, sed.uom, sed.t_warehouse as warehouse
		from `tabStock Entry Detail` sed
		inner join `tabStock Entry` se on se.name = sed.parent
		left join `tabStock Entry Type` setype on setype.name = se.stock_entry_type
		where se.name in %(documents)s
			and se.docstatus = 1
			and coalesce(setype.purpose, se.purpose) in %(purposes)s
			and sed.t_warehouse is not null
			and sed.t_warehouse != ''
			and sed.qty > 0
			{_stock_entry_warehouse_condition(warehouse)}
			{"and se.company = %(company)s" if company else ""}
		order by se.posting_date asc, se.name asc, sed.idx asc
		""",
		{"documents": documents, "purposes": RECEIVING_STOCK_ENTRY_PURPOSES, "company": company, "warehouse": warehouse},
		as_dict=True,
	)


def _get_purchase_receipt_rows(documents, company=None, warehouse=None):
	return frappe.db.sql(
		f"""
		select pr.name as source_name, 'Purchase Receipt' as source_doctype, pri.item_code,
			pri.qty, pri.uom, pri.warehouse
		from `tabPurchase Receipt Item` pri
		inner join `tabPurchase Receipt` pr on pr.name = pri.parent
		where pr.name in %(documents)s
			and pr.docstatus = 1
			and pri.qty > 0
			{_warehouse_condition("pri", warehouse)}
			{"and pr.company = %(company)s" if company else ""}
		order by pr.posting_date asc, pr.name asc, pri.idx asc
		""",
		{"documents": documents, "company": company, "warehouse": warehouse},
		as_dict=True,
	)


def _get_warehouse_transfer_rows(documents, company=None, warehouse=None):
	return frappe.db.sql(
		f"""
		select wt.name as source_name, 'Warehouse Transfer' as source_doctype, wtd.item_code,
			(coalesce(wtd.issued_qty, 0) - coalesce(wtd.received_qty, 0)) as qty,
			wtd.uom, wt.target_warehouse as warehouse
		from `tabWarehouse Transfer Details` wtd
		inner join `tabWarehouse Transfer` wt on wt.name = wtd.parent
		where wt.name in %(documents)s
			and wt.docstatus = 1
			and wt.transfer_status = 'Transferred'
			and coalesce(wtd.issued_qty, 0) > coalesce(wtd.received_qty, 0)
			{"and wt.target_warehouse = %(warehouse)s" if warehouse else ""}
			{"and wt.target_company = %(company)s" if company else ""}
		order by wt.date_transferred asc, wt.name asc, wtd.idx asc
		""",
		{"documents": documents, "company": company, "warehouse": warehouse},
		as_dict=True,
	)


def _get_delivery_note_return_rows(documents, company=None, warehouse=None):
	return frappe.db.sql(
		f"""
		select dn.name as source_name, 'Delivery Note' as source_doctype, dni.item_code,
			abs(dni.qty) as qty, dni.uom, dni.warehouse
		from `tabDelivery Note Item` dni
		inner join `tabDelivery Note` dn on dn.name = dni.parent
		where dn.name in %(documents)s
			and dn.docstatus = 1
			and dn.is_return = 1
			and dni.qty < 0
			{_warehouse_condition("dni", warehouse)}
			{"and dn.company = %(company)s" if company else ""}
		order by dn.posting_date asc, dn.name asc, dni.idx asc
		""",
		{"documents": documents, "company": company, "warehouse": warehouse},
		as_dict=True,
	)


def _get_sales_invoice_return_rows(documents, company=None, warehouse=None):
	return frappe.db.sql(
		f"""
		select si.name as source_name, 'Sales Invoice' as source_doctype, sii.item_code,
			abs(sii.qty) as qty, sii.uom, sii.warehouse
		from `tabSales Invoice Item` sii
		inner join `tabSales Invoice` si on si.name = sii.parent
		where si.name in %(documents)s
			and si.docstatus = 1
			and si.is_return = 1
			and si.update_stock = 1
			and sii.qty < 0
			{_warehouse_condition("sii", warehouse)}
			{"and si.company = %(company)s" if company else ""}
		order by si.posting_date asc, si.name asc, sii.idx asc
		""",
		{"documents": documents, "company": company, "warehouse": warehouse},
		as_dict=True,
	)


def _consolidate_items(rows):
	items = defaultdict(lambda: {"qty": 0})
	for row in rows:
		key = (row.item_code, row.uom)
		items[key].update({"item_code": row.item_code, "uom": row.uom})
		items[key]["qty"] += flt(row.qty)

	return [
		{
			"item_code": item["item_code"],
			"uom": item["uom"],
			"qty": item["qty"],
			"putaway_qty": 0,
			"remaining_qty": item["qty"],
		}
		for item in items.values()
	]
