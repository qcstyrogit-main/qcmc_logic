import frappe
from frappe import _
from frappe.utils import flt


@frappe.whitelist()
def get_sales_order_items_for_work_order(sales_order=None, item_code=None):
	conditions = [
		"so.docstatus = 1",
		"ifnull(so.status, '') not in ('Closed', 'On Hold')",
		"ifnull(soi.delivered_by_supplier, 0) = 0",
	]
	values = {}

	if sales_order:
		conditions.append("so.name = %(sales_order)s")
		values["sales_order"] = sales_order

	if item_code:
		conditions.append("soi.item_code = %(item_code)s")
		values["item_code"] = item_code

	rows = frappe.db.sql(
		"""
		select
			so.name as sales_order,
			so.customer,
			so.customer_name,
			soi.name as sales_order_item,
			soi.item_code,
			soi.item_name,
			soi.description,
			soi.qty,
			soi.uom,
			soi.stock_uom,
			soi.conversion_factor,
			soi.produced_qty,
			soi.delivery_date
		from `tabSales Order` so
		inner join `tabSales Order Item` soi on soi.parent = so.name
		where {conditions}
		order by so.transaction_date desc, so.name desc, soi.idx
		limit 200
		""".format(conditions=" and ".join(conditions)),
		values,
		as_dict=True,
	)

	result = []
	for row in rows:
		row.pending_qty = flt(row.qty) - flt(row.produced_qty)
		if row.pending_qty > 0:
			result.append(row)

	return result


@frappe.whitelist()
def get_bom_secondary_outputs(bom_no):
	if not bom_no:
		return []

	return frappe.get_all(
		"BOM Secondary Item",
		filters={"parent": bom_no, "parenttype": "BOM"},
		fields=["name", "item_code", "item_name", "type", "stock_uom", "qty", "stock_qty"],
		order_by="idx",
	)


def validate_work_order_secondary_sales_order_items(doc, method=None):
	if doc.doctype != "Work Order":
		return
	if not doc.meta.has_field("custom_eps_sales_order_items"):
		return

	for row in doc.get("custom_eps_sales_order_items", []):
		validate_work_order_sales_order_item(row)


def validate_work_order_sales_order_item(row):
	if not row.sales_order or not row.sales_order_item:
		frappe.throw(
			_("Row #{0}: Sales Order and Sales Order Item are required.").format(row.idx)
		)

	so_item = frappe.db.get_value(
		"Sales Order Item",
		row.sales_order_item,
		["parent", "item_code"],
		as_dict=True,
	)
	if not so_item:
		frappe.throw(_("Row #{0}: Sales Order Item {1} was not found.").format(row.idx, row.sales_order_item))

	if so_item.parent != row.sales_order:
		frappe.throw(
			_("Row #{0}: Sales Order Item {1} does not belong to Sales Order {2}.").format(
				row.idx,
				frappe.bold(row.sales_order_item),
				frappe.bold(row.sales_order),
			)
		)

	if so_item.item_code != row.item_code:
		frappe.throw(
			_("Row #{0}: Sales Order Item {1} is for item {2}, not {3}.").format(
				row.idx,
				frappe.bold(row.sales_order_item),
				frappe.bold(so_item.item_code),
				frappe.bold(row.item_code),
			)
		)
