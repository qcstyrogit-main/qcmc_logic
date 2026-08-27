import frappe
from frappe.utils import escape_html, flt

from erpnext.stock.dashboard.warehouse_capacity_dashboard import (
	get_filters,
	get_warehouse_filter_based_on_permissions,
)
from erpnext.stock.utils import get_stock_balance

from qcmc_logic.overrides.putaway_rule_dimension import get_dimension_stock_balance


@frappe.whitelist()
def get_data(
	item_code=None,
	warehouse=None,
	parent_warehouse=None,
	company=None,
	start=0,
	sort_by="stock_capacity",
	sort_order="desc",
):
	"""Return capacity per exact Putaway Rule inventory dimension."""
	filters = get_filters(item_code, warehouse, parent_warehouse, company)
	no_permission, filters = get_warehouse_filter_based_on_permissions(filters)
	if no_permission:
		return []

	fields = ["name", "item_code", "warehouse", "stock_capacity", "company"]
	if frappe.get_meta("Putaway Rule").has_field("location"):
		fields.append("location")
	rows = frappe.get_all(
		"Putaway Rule",
		fields=fields,
		filters=filters,
		limit_page_length=0,
	)
	for row in rows:
		location = row.get("location")
		if location:
			balance = get_dimension_stock_balance(
				row.item_code, row.warehouse, {"location": location}
			)
		else:
			balance = get_stock_balance(row.item_code, row.warehouse) or 0
		row.update(
			putaway_rule=row.name,
			warehouse=escape_html(row.warehouse),
			item_code=escape_html(row.item_code),
			company=escape_html(row.company),
			location=escape_html(location or ""),
			actual_qty=balance,
			percent_occupied=flt(
				(flt(balance) / flt(row.stock_capacity)) * 100 if row.stock_capacity else 0,
				0,
			),
		)

	direction = -1 if sort_order == "desc" else 1
	rows = sorted(
		rows,
		key=lambda row: (flt(row.get(sort_by)) * direction, row.name),
	)
	start = int(start or 0)
	return rows[start : start + 11]
