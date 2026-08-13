import json

import frappe
from frappe import _
from frappe.utils import flt


def warehouse_transfer_exists(pick_list_name):
	return frappe.db.exists(
		"Warehouse Transfer Details",
		{"against_pick_list": pick_list_name, "docstatus": 1},
	)


@frappe.whitelist()
def create_warehouse_transfer(pick_list, target_warehouse=None, transfer_type="Warehouse Transfer"):
	pick_list = frappe.get_doc(json.loads(pick_list))
	validate_pick_list_for_warehouse_transfer(pick_list)

	if warehouse_transfer_exists(pick_list.name):
		frappe.msgprint(_("Warehouse Transfer has already been created against this Pick List"))
		return

	source_warehouse = get_pick_list_source_warehouse(pick_list)
	target_warehouse = target_warehouse or get_pick_list_target_warehouse(pick_list)

	if not target_warehouse:
		frappe.throw(_("Target Warehouse is required to create Warehouse Transfer from Pick List."))

	warehouse_transfer = frappe.new_doc("Warehouse Transfer")
	warehouse_transfer.transfer_type = transfer_type
	warehouse_transfer.source_warehouse = source_warehouse
	warehouse_transfer.target_warehouse = target_warehouse
	warehouse_transfer.source_company = pick_list.company
	warehouse_transfer.transfer_status = "Draft"

	for location in pick_list.get("locations"):
		remaining_qty = flt(location.picked_qty) - flt(location.delivered_qty)
		if remaining_qty <= 0:
			continue

		row = warehouse_transfer.append(
			"transfer_items",
			{
				"item_code": location.item_code,
				"item_name": location.item_name,
				"uom": location.uom,
				"issued_qty": remaining_qty,
				"received_qty": 0,
				"reference_doc": pick_list.name,
				"against_pick_list": pick_list.name,
				"pick_list_item": location.name,
				"material_request": location.material_request,
				"material_request_item": location.material_request_item,
			},
		)
		copy_inventory_dimensions(location, row)

	if not warehouse_transfer.get("transfer_items"):
		frappe.throw(_("No pending picked items found for Warehouse Transfer."))

	return warehouse_transfer.as_dict()


def validate_pick_list_for_warehouse_transfer(pick_list):
	if pick_list.docstatus != 1:
		frappe.throw(_("Pick List must be submitted."))
	if pick_list.purpose != "Material Transfer":
		frappe.throw(_("Warehouse Transfer can only be created for Material Transfer Pick Lists."))
	if pick_list.status == "Completed":
		frappe.throw(_("Pick List is already completed."))


def get_pick_list_source_warehouse(pick_list):
	warehouses = {
		row.warehouse
		for row in pick_list.get("locations")
		if row.warehouse and flt(row.picked_qty) > flt(row.delivered_qty)
	}
	if not warehouses:
		frappe.throw(_("No pending warehouses found in Pick List."))
	if len(warehouses) > 1:
		frappe.throw(_("Warehouse Transfer requires Pick List rows from a single source warehouse."))
	return warehouses.pop()


def get_pick_list_target_warehouse(pick_list):
	if not pick_list.material_request:
		return None

	warehouses = {
		row.warehouse
		for row in frappe.get_all(
			"Material Request Item",
			filters={"parent": pick_list.material_request},
			fields=["warehouse"],
		)
		if row.warehouse
	}
	return warehouses.pop() if len(warehouses) == 1 else None


def copy_inventory_dimensions(source, target):
	for fieldname in get_inventory_dimension_fieldnames():
		if source.get(fieldname):
			target.set(fieldname, source.get(fieldname))


def get_inventory_dimension_fieldnames():
	if not frappe.db.exists("DocType", "Inventory Dimension"):
		return []

	return frappe.get_all(
		"Inventory Dimension",
		filters={"disabled": 0},
		pluck="fieldname",
	)


def validate_pick_list_references(doc):
	for row in doc.get("transfer_items") or []:
		if not row.get("pick_list_item"):
			continue

		pick_list_item = frappe.db.get_value(
			"Pick List Item",
			row.pick_list_item,
			["parent", "item_code", "warehouse", "picked_qty", "delivered_qty"],
			as_dict=True,
		)
		if not pick_list_item:
			frappe.throw(_("Pick List Item {0} does not exist.").format(row.pick_list_item))
		if row.get("against_pick_list") and row.against_pick_list != pick_list_item.parent:
			frappe.throw(_("Row {0}: Pick List reference does not match Pick List Item.").format(row.idx))
		if row.item_code != pick_list_item.item_code:
			frappe.throw(_("Row {0}: Item does not match the Pick List Item.").format(row.idx))
		if doc.source_warehouse != pick_list_item.warehouse:
			frappe.throw(_("Row {0}: Source Warehouse does not match the Pick List Item.").format(row.idx))
		if flt(row.issued_qty) > flt(pick_list_item.picked_qty) - flt(pick_list_item.delivered_qty):
			frappe.throw(_("Row {0}: Issued Qty exceeds pending Pick List quantity.").format(row.idx))


def update_pick_list_progress(docname):
	pick_lists = get_referenced_pick_lists(docname)
	for pick_list_name in pick_lists:
		update_pick_list_delivered_qty(pick_list_name)
		update_pick_list_status(pick_list_name)


def get_referenced_pick_lists(docname):
	return frappe.db.sql_list(
		"""
		select distinct against_pick_list
		from `tabWarehouse Transfer Details`
		where parent = %s and ifnull(against_pick_list, '') != ''
		""",
		docname,
	)


def update_pick_list_delivered_qty(pick_list_name):
	rows = frappe.db.sql(
		"""
		select
			wtd.pick_list_item,
			sum(wtd.issued_qty) as delivered_qty
		from `tabWarehouse Transfer Details` wtd
		inner join `tabWarehouse Transfer` wt on wt.name = wtd.parent
		where
			wt.docstatus = 1
			and ifnull(wt.transfer_status, '') in ('Transferred', 'Received')
			and wtd.against_pick_list = %s
			and ifnull(wtd.pick_list_item, '') != ''
		group by wtd.pick_list_item
		""",
		pick_list_name,
		as_dict=True,
	)
	delivered_by_item = {row.pick_list_item: flt(row.delivered_qty) for row in rows}

	for item_name in frappe.get_all("Pick List Item", {"parent": pick_list_name}, pluck="name"):
		frappe.db.set_value(
			"Pick List Item",
			item_name,
			"delivered_qty",
			delivered_by_item.get(item_name, 0),
			update_modified=False,
		)


def update_pick_list_status(pick_list_name):
	pick_list = frappe.get_doc("Pick List", pick_list_name)
	total_picked = sum(flt(row.picked_qty) for row in pick_list.locations)
	total_delivered = sum(flt(row.delivered_qty) for row in pick_list.locations)

	per_delivered = (total_delivered / total_picked * 100) if total_picked else 0
	if per_delivered >= 100:
		delivery_status = "Fully Delivered"
		status = "Completed"
	elif per_delivered > 0:
		delivery_status = "Partly Delivered"
		status = "Partly Delivered"
	else:
		delivery_status = "Not Delivered"
		status = "Open" if pick_list.docstatus == 1 else "Draft"

	frappe.db.set_value(
		"Pick List",
		pick_list_name,
		{
			"per_delivered": per_delivered,
			"delivery_status": delivery_status,
			"status": status,
		},
		update_modified=False,
	)
