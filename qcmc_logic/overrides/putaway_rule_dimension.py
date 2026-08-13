import copy
import json
from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import cint, cstr, floor, flt, nowdate

from erpnext.stock.doctype.inventory_dimension.inventory_dimension import get_inventory_dimensions
from erpnext.stock.doctype.serial_no.serial_no import get_serial_nos
from erpnext.stock.utils import get_stock_balance


RECEIVING_STOCK_ENTRY_PURPOSES = {
	"Material Receipt",
	"Material Transfer",
	"Manufacture",
	"Repack",
}


def get_dimension_fields_for_doctype(doctype):
	meta = frappe.get_meta(doctype)
	return [
		dimension.get("fieldname")
		for dimension in get_inventory_dimensions()
		if dimension.get("fieldname") and meta.has_field(dimension.get("fieldname"))
	]


def get_dimension_values(doc):
	return {
		fieldname: doc.get(fieldname)
		for fieldname in get_dimension_fields_for_doctype(doc.doctype)
		if doc.get(fieldname)
	}


def get_rule_dimension_fields():
	return get_dimension_fields_for_doctype("Putaway Rule")


def get_rule_dimension_values(rule):
	return {
		fieldname: rule.get(fieldname)
		for fieldname in get_rule_dimension_fields()
		if rule.get(fieldname)
	}


def apply_dimension_putaway_rule(doctype, items, company, sync=None, purpose=None):
	if isinstance(items, str):
		items = json.loads(items)

	if doctype == "Stock Entry" and purpose not in RECEIVING_STOCK_ENTRY_PURPOSES:
		return items if sync and json.loads(sync) else None

	items_not_accommodated, updated_table = [], []
	item_wise_rules = defaultdict(list)

	for item in items:
		if isinstance(item, dict):
			item = frappe._dict(item)

		if doctype == "Stock Entry" and not is_receiving_stock_entry_row(item, purpose):
			updated_table.append(item)
			continue

		source_warehouse = item.get("s_warehouse")
		serial_nos = get_serial_nos(item.get("serial_no")) if item.get("serial_no") else []
		item.conversion_factor = flt(item.conversion_factor) or 1.0

		pending_qty = flt(item.qty)
		pending_stock_qty = flt(item.transfer_qty) if doctype == "Stock Entry" else flt(item.stock_qty)
		item_code = item.get("item_code")
		uom_must_be_whole_number = frappe.db.get_value("UOM", item.uom, "must_be_whole_number")

		if not pending_qty or not item_code:
			updated_table = add_row(
				item,
				pending_qty,
				source_warehouse or item.get("warehouse"),
				updated_table,
				serial_nos=serial_nos,
			)
			continue

		at_capacity, rules = get_ordered_dimension_putaway_rules(
			item_code,
			company,
			source_warehouse=source_warehouse,
			item_dimensions=get_dimension_values(item),
		)

		if not rules:
			warehouse = get_default_receiving_warehouse(item, source_warehouse)
			if at_capacity:
				items_not_accommodated.append([item_code, pending_qty])
			else:
				updated_table = add_row(item, pending_qty, warehouse, updated_table, serial_nos=serial_nos)
			continue

		key = get_item_rule_key(doctype, purpose, item_code, source_warehouse, item)
		if not item_wise_rules[key]:
			item_wise_rules[key] = rules

		for rule in item_wise_rules[key]:
			if pending_stock_qty > 0 and rule.free_space:
				stock_qty_to_allocate = (
					flt(rule.free_space) if pending_stock_qty >= flt(rule.free_space) else pending_stock_qty
				)
				qty_to_allocate = stock_qty_to_allocate / item.conversion_factor

				if uom_must_be_whole_number:
					qty_to_allocate = floor(qty_to_allocate)
					stock_qty_to_allocate = qty_to_allocate * item.conversion_factor

				if not qty_to_allocate:
					break

				updated_table = add_row(
					item,
					qty_to_allocate,
					rule.warehouse,
					updated_table,
					rule.name,
					rule_dimensions=get_rule_dimension_values(rule),
					serial_nos=serial_nos,
				)
				pending_stock_qty -= stock_qty_to_allocate
				pending_qty -= qty_to_allocate
				rule["free_space"] -= stock_qty_to_allocate

				if pending_stock_qty <= 0:
					break

		if pending_stock_qty > 0:
			items_not_accommodated.append([item_code, pending_qty])

	if items_not_accommodated:
		show_unassigned_items_message(items_not_accommodated)

	if updated_table and _items_changed(items, updated_table, doctype):
		items[:] = updated_table
		frappe.msgprint(_("Applied putaway rules."), alert=True)

	if sync and json.loads(sync):
		return items


def is_receiving_stock_entry_row(item, purpose):
	if purpose in {"Material Receipt", "Manufacture", "Repack"}:
		return bool(item.get("t_warehouse")) and flt(item.get("qty")) > 0

	if purpose == "Material Transfer":
		return bool(item.get("t_warehouse")) and flt(item.get("qty")) > 0

	return False


def get_default_receiving_warehouse(item, source_warehouse=None):
	if item.get("t_warehouse"):
		return item.get("t_warehouse")
	return source_warehouse or item.get("warehouse")


def get_item_rule_key(doctype, purpose, item_code, source_warehouse, item):
	dimension_key = tuple(sorted(get_dimension_values(item).items()))
	if doctype == "Stock Entry" and purpose == "Material Transfer" and source_warehouse:
		return (item_code, source_warehouse, dimension_key)
	return (item_code, dimension_key)


def get_ordered_dimension_putaway_rules(item_code, company, source_warehouse=None, item_dimensions=None):
	filters = {"item_code": item_code, "company": company, "disable": 0}
	if source_warehouse:
		filters.update({"warehouse": ["!=", source_warehouse]})

	fields = ["name", "item_code", "stock_capacity", "priority", "warehouse", *get_rule_dimension_fields()]
	rules = frappe.get_all(
		"Putaway Rule",
		fields=fields,
		filters=filters,
		order_by="priority asc, capacity desc",
	)

	rules = filter_rules_by_item_dimensions(rules, item_dimensions or {})
	if not rules:
		return False, None

	vacant_rules = []
	for rule in rules:
		dimensions = get_rule_dimension_values(rule)
		balance_qty = get_stock_balance(
			rule.item_code,
			rule.warehouse,
			nowdate(),
			inventory_dimensions_dict=dimensions or None,
		)
		free_space = flt(rule.stock_capacity) - flt(balance_qty)
		if free_space > 0:
			rule["free_space"] = free_space
			vacant_rules.append(rule)

	if not vacant_rules:
		return True, None

	return False, sorted(vacant_rules, key=lambda i: (i["priority"], -i["free_space"]))


def filter_rules_by_item_dimensions(rules, item_dimensions):
	if not item_dimensions:
		return rules

	filtered = []
	for rule in rules:
		rule_dimensions = get_rule_dimension_values(rule)
		if all(rule_dimensions.get(fieldname) == value for fieldname, value in item_dimensions.items()):
			filtered.append(rule)

	return filtered


def add_row(item, to_allocate, warehouse, updated_table, rule=None, rule_dimensions=None, serial_nos=None):
	new_row = copy.deepcopy(item)
	new_row.idx = 1 if not updated_table else cint(updated_table[-1].idx) + 1
	new_row.name = None
	new_row.qty = to_allocate

	if item.doctype == "Stock Entry Detail":
		new_row.t_warehouse = warehouse
		new_row.transfer_qty = flt(to_allocate) * flt(new_row.conversion_factor)
	else:
		new_row.stock_qty = flt(to_allocate) * flt(new_row.conversion_factor)
		new_row.warehouse = warehouse
		new_row.rejected_qty = 0
		new_row.received_qty = to_allocate

	if rule:
		new_row.putaway_rule = rule

	for fieldname, value in (rule_dimensions or {}).items():
		if frappe.get_meta(new_row.doctype).has_field(fieldname):
			new_row.set(fieldname, value)

	if serial_nos:
		new_row.serial_no = "\n".join(serial_nos[0 : cint(to_allocate)])
		del serial_nos[0 : cint(to_allocate)]

	new_row.serial_and_batch_bundle = ""
	updated_table.append(new_row)
	return updated_table


def _items_changed(old, new, doctype):
	if len(old) != len(new):
		return True

	old = [frappe._dict(item) if isinstance(item, dict) else item for item in old]
	dimension_fields = get_dimension_fields_for_doctype(
		"Stock Entry Detail" if doctype == "Stock Entry" else old[0].doctype
	) if old else []

	if doctype == "Stock Entry":
		compare_keys = ("item_code", "t_warehouse", "transfer_qty", "serial_no", *dimension_fields)
		sort_key = lambda item: (
			item.item_code,
			cstr(item.t_warehouse),
			flt(item.transfer_qty),
			cstr(item.serial_no),
			*[cstr(item.get(fieldname)) for fieldname in dimension_fields],
		)
	else:
		compare_keys = ("item_code", "warehouse", "stock_qty", "received_qty", "serial_no", *dimension_fields)
		sort_key = lambda item: (
			item.item_code,
			cstr(item.warehouse),
			flt(item.stock_qty),
			flt(item.received_qty),
			cstr(item.serial_no),
			*[cstr(item.get(fieldname)) for fieldname in dimension_fields],
		)

	old_sorted = sorted(old, key=sort_key)
	new_sorted = sorted(new, key=sort_key)
	for old_item, new_item in zip(old_sorted, new_sorted, strict=False):
		for key in compare_keys:
			if old_item.get(key) != new_item.get(key):
				return True
	return False


def show_unassigned_items_message(items_not_accommodated):
	rows = ""
	for item_code, qty in items_not_accommodated:
		rows += f"<tr><td>{frappe.utils.get_link_to_form('Item', item_code)}</td><td>{frappe.bold(qty)}</td></tr>"

	msg = _("The following Items, having Putaway Rules, could not be accommodated:") + "<br><br>"
	msg += """
		<table class="table">
			<thead><td>{0}</td><td>{1}</td></thead>
			{2}
		</table>
	""".format(_("Item"), _("Unassigned Qty"), rows)

	frappe.msgprint(msg, title=_("Insufficient Capacity"), is_minimizable=True, wide=True)


def get_dimension_putaway_for_item(item_code, company, source_warehouse=None, item_dimensions=None):
	_, rules = get_ordered_dimension_putaway_rules(
		item_code,
		company,
		source_warehouse=source_warehouse,
		item_dimensions=item_dimensions or {},
	)
	return rules[0] if rules else None


def validate_dimension_putaway_capacity(doc):
	if doc.doctype == "Purchase Invoice" and doc.get("update_stock") == 0:
		return

	if not frappe.get_all("Putaway Rule", limit=1):
		return

	rule_map = defaultdict(dict)
	for item in doc.get("items"):
		rule = get_item_putaway_rule(doc, item)
		if not rule or rule.get("disable"):
			continue

		stock_qty = get_item_stock_qty(doc, item)
		if stock_qty <= 0:
			continue

		rule_name = rule.name
		if not rule_map[rule_name]:
			rule_map[rule_name]["warehouse"] = get_receiving_warehouse(doc, item, rule)
			rule_map[rule_name]["item"] = item.get("item_code")
			rule_map[rule_name]["qty_put"] = 0
			rule_map[rule_name]["capacity"] = get_available_dimension_putaway_capacity(rule)

		rule_map[rule_name]["qty_put"] += flt(stock_qty)

	for rule_name, values in rule_map.items():
		if flt(values["qty_put"]) > flt(values["capacity"]):
			frappe.throw(
				msg=_("{0} qty of Item {1} is being received into Warehouse {2} with capacity {3}.").format(
					frappe.bold(values["qty_put"]),
					frappe.bold(values["item"]),
					frappe.bold(values["warehouse"]),
					frappe.bold(values["capacity"]),
				)
				+ "<br><br>"
				+ _("Please adjust the qty or edit {0} to proceed.").format(
					frappe.utils.get_link_to_form("Putaway Rule", rule_name)
				),
				title=_("Over Receipt"),
			)


def get_item_putaway_rule(doc, item):
	rule_name = item.get("putaway_rule")
	if rule_name:
		return frappe.get_cached_doc("Putaway Rule", rule_name)

	source_warehouse = item.get("s_warehouse") if doc.doctype == "Stock Entry" else None
	return get_dimension_putaway_for_item(
		item.get("item_code"),
		doc.company,
		source_warehouse=source_warehouse,
		item_dimensions=get_dimension_values(item),
	)


def get_item_stock_qty(doc, item):
	if doc.doctype == "Stock Reconciliation":
		return flt(item.qty)
	if doc.doctype == "Stock Entry":
		return flt(item.transfer_qty)
	return flt(item.stock_qty)


def get_receiving_warehouse(doc, item, rule):
	if rule:
		return rule.warehouse
	if doc.doctype == "Stock Entry":
		return item.get("t_warehouse")
	return item.get("warehouse")


def get_available_dimension_putaway_capacity(rule):
	if isinstance(rule, str):
		rule = frappe.get_cached_doc("Putaway Rule", rule)

	balance_qty = get_dimension_putaway_balance(rule)
	free_space = flt(rule.stock_capacity) - flt(balance_qty)
	return free_space if free_space > 0 else 0


def get_dimension_putaway_balance(rule):
	balance_qty = get_stock_balance(
		rule.item_code,
		rule.warehouse,
		nowdate(),
		inventory_dimensions_dict=get_rule_dimension_values(rule) or None,
	)
	return flt(balance_qty)
