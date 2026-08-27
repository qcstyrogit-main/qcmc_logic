import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	create_custom_fields({
		"Storage Location": [
			{"fieldname": "custom_warehouse", "label": "Warehouse", "fieldtype": "Link", "options": "Warehouse", "insert_after": "disabled", "in_list_view": 1, "reqd": 1},
			{"fieldname": "custom_restricted_item", "label": "Restricted Item", "fieldtype": "Link", "options": "Item", "insert_after": "custom_warehouse", "description": "Optional. Leave blank to allow any item."},
			{"fieldname": "custom_storage_capacity", "label": "Storage Capacity", "fieldtype": "Float", "insert_after": "custom_restricted_item", "description": "Capacity in the received item's Stock UOM."},
		],
	}, update=True)

	# Preserve existing configuration where one location has one unambiguous
	# Putaway Rule mapping. Future override validation reads only these fields.
	for location in frappe.get_all("Storage Location", pluck="name"):
		rules = frappe.get_all(
			"Putaway Rule",
			filters={"location": location},
			fields=["item_code", "warehouse", "stock_capacity"],
		)
		warehouses = {rule.warehouse for rule in rules if rule.warehouse}
		items = {rule.item_code for rule in rules if rule.item_code}
		values = {}
		if len(warehouses) == 1:
			values["custom_warehouse"] = next(iter(warehouses))
		if len(items) == 1:
			values["custom_restricted_item"] = next(iter(items))
		if rules:
			values["custom_storage_capacity"] = max(float(rule.stock_capacity or 0) for rule in rules)
		if values:
			frappe.db.set_value("Storage Location", location, values, update_modified=False)

	# A no-rule leaf can inherit an unambiguous warehouse and typical capacity
	# from rule-backed siblings under the same parent. It remains unrestricted
	# by item because no explicit restriction was configured on that leaf.
	for location in frappe.get_all(
		"Storage Location",
		filters={"is_group": 0},
		fields=["name", "parent_storage_location", "custom_warehouse", "custom_storage_capacity"],
	):
		if location.custom_warehouse and float(location.custom_storage_capacity or 0) > 0:
			continue
		parent = location.parent_storage_location
		if not parent:
			continue
		sibling_names = frappe.get_all(
			"Storage Location", filters={"parent_storage_location": parent}, pluck="name"
		)
		sibling_rules = frappe.get_all(
			"Putaway Rule",
			filters={"location": ["in", sibling_names]},
			fields=["warehouse", "stock_capacity"],
		)
		warehouses = {rule.warehouse for rule in sibling_rules if rule.warehouse}
		capacities = [float(rule.stock_capacity or 0) for rule in sibling_rules if float(rule.stock_capacity or 0) > 0]
		values = {}
		if not location.custom_warehouse and len(warehouses) == 1:
			values["custom_warehouse"] = next(iter(warehouses))
		if not float(location.custom_storage_capacity or 0) and capacities:
			values["custom_storage_capacity"] = max(capacities)
		if values:
			frappe.db.set_value("Storage Location", location.name, values, update_modified=False)

	# Persist an unambiguous warehouse on group locations as well. Runtime QR
	# and allocation code never infer it from hierarchy or names.
	for group in frappe.get_all("Storage Location", filters={"is_group": 1}, fields=["name", "lft", "rgt", "custom_warehouse"]):
		if group.custom_warehouse:
			continue
		warehouses = set(frappe.get_all(
			"Storage Location",
			filters={"lft": [">", group.lft], "rgt": ["<", group.rgt], "custom_warehouse": ["is", "set"]},
			pluck="custom_warehouse",
		))
		warehouses.discard("")
		if len(warehouses) == 1:
			frappe.db.set_value("Storage Location", group.name, "custom_warehouse", next(iter(warehouses)), update_modified=False)

	# Once group warehouses are persisted, copy the explicit warehouse of the
	# direct parent to otherwise-unconfigured children. This is migration-only;
	# runtime validation always reads the child's own stored warehouse.
	for location in frappe.get_all(
		"Storage Location",
		filters={"custom_warehouse": ["is", "not set"], "parent_storage_location": ["is", "set"]},
		fields=["name", "parent_storage_location"],
	):
		parent_warehouse = frappe.db.get_value(
			"Storage Location", location.parent_storage_location, "custom_warehouse"
		)
		if parent_warehouse:
			frappe.db.set_value(
				"Storage Location", location.name, "custom_warehouse", parent_warehouse, update_modified=False
			)

	# Refresh persisted QR payloads from the authoritative Storage Location
	# warehouse. Printed QR pages also regenerate this value at request time.
	for name in frappe.get_all("Storage Location", pluck="name"):
		doc = frappe.get_doc("Storage Location", name)
		doc._set_qr_payload()
		frappe.db.set_value("Storage Location", name, "qr_payload", doc.qr_payload, update_modified=False)
