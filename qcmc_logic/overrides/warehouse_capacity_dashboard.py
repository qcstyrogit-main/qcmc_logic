import frappe
from frappe.desk.reportview import build_match_conditions
from frappe.utils import escape_html, flt, nowdate

from erpnext.stock.utils import get_stock_balance
from qcmc_logic.overrides.putaway_rule_dimension import get_rule_dimension_fields, get_rule_dimension_values


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
	filters = get_filters(item_code, warehouse, parent_warehouse, company)
	no_permission, filters = get_warehouse_filter_based_on_permissions(filters)

	if no_permission:
		return []

	capacity_data = get_warehouse_capacity_data(filters, start)
	asc_desc = -1 if sort_order == "desc" else 1

	return sorted(capacity_data, key=lambda i: (i.get(sort_by) or 0) * asc_desc)


def get_filters(item_code=None, warehouse=None, parent_warehouse=None, company=None):
	filters = [["disable", "=", 0]]

	if item_code:
		filters.append(["item_code", "=", item_code])
	if warehouse:
		filters.append(["warehouse", "=", warehouse])
	if company:
		filters.append(["company", "=", company])
	if parent_warehouse:
		lft, rgt = frappe.db.get_value("Warehouse", parent_warehouse, ["lft", "rgt"])
		warehouses = frappe.db.sql_list(
			"""
			select name from `tabWarehouse`
			where lft >= %s and rgt <= %s
			""",
			(lft, rgt),
		)
		filters.append(["warehouse", "in", warehouses])

	return filters


def get_warehouse_filter_based_on_permissions(filters):
	try:
		if build_match_conditions("Warehouse", user=frappe.session.user):
			filters.append(["warehouse", "in", [w.name for w in frappe.get_list("Warehouse")]])
		return False, filters
	except frappe.PermissionError:
		return True, []


def get_warehouse_capacity_data(filters, start):
	dimension_fields = get_rule_dimension_fields()
	capacity_data = frappe.db.get_all(
		"Putaway Rule",
		fields=["name", "item_code", "warehouse", "stock_capacity", "company", *dimension_fields],
		filters=filters,
		limit_start=start,
		limit_page_length=11,
	)

	for entry in capacity_data:
		dimensions = get_rule_dimension_values(entry)
		balance_qty = (
			get_stock_balance(
				entry.item_code,
				entry.warehouse,
				nowdate(),
				inventory_dimensions_dict=dimensions or None,
			)
			or 0
		)
		entry.update(
			{
				"warehouse": escape_html(entry.warehouse),
				"item_code": escape_html(entry.item_code),
				"company": escape_html(entry.company),
				"actual_qty": balance_qty,
				"percent_occupied": flt((flt(balance_qty) / flt(entry.stock_capacity)) * 100, 0),
				"inventory_dimensions": get_dimension_summary(dimensions),
			}
		)

	return capacity_data


def get_dimension_summary(dimensions):
	if not dimensions:
		return ""

	return ", ".join(
		"{0}: {1}".format(frappe.unscrub(fieldname), value)
		for fieldname, value in dimensions.items()
	)
