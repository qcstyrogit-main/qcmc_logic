import copy
import json

import frappe
from frappe import _
from frappe.utils import flt
from erpnext.stock.doctype.pick_list.pick_list import (
	PickList,
	create_stock_entry as erpnext_create_stock_entry,
)


class CustomPickList(PickList):
	def before_save(self):
		super().before_save()
		if not self.pick_manually:
			assign_storage_locations(self)

	def on_cancel(self):
		from qcmc_logic.delivery_note_pick_list import unlink_cancelled_pick_list
		# Validate linked Delivery Notes before calling ERPNext cancellation.
		# The actual unlink happens after the parent cancellation succeeds.
		delivery_rows = frappe.db.get_all("Delivery Note Item",
			filters={"against_pick_list": self.name}, fields=["parent"])
		for name in {row.parent for row in delivery_rows}:
			if frappe.db.get_value("Delivery Note", name, "docstatus") == 1:
				frappe.throw(_("Cancel Delivery Note {0} before cancelling its linked Pick List.").format(
					frappe.bold(name)))
		# A posted Warehouse Transfer has already issued stock and cannot lose
		# its picking audit reference through Pick List cancellation.
		linked = frappe.db.get_all("Warehouse Transfer Details",
			filters={"against_pick_list": self.name}, fields=["parent"], distinct=True)
		for row in linked:
			if frappe.db.get_value("Warehouse Transfer", row.parent, "docstatus") == 1:
				frappe.throw(_("Cancel Warehouse Transfer {0} before cancelling its linked Pick List.").format(
					frappe.bold(row.parent)))
		# Keep submitted manufacturing Stock Entries linked to their audit
		# document; require reversal before the Pick List is cancelled.
		linked_stock_entries = frappe.db.get_all("Stock Entry",
			filters={"pick_list": self.name}, fields=["name", "docstatus"])
		for entry in linked_stock_entries:
			if entry.docstatus == 1:
				frappe.throw(_("Cancel Stock Entry {0} before cancelling its Pick List.").format(
					frappe.bold(entry.name)))
		super().on_cancel()
		for entry in linked_stock_entries:
			if entry.docstatus == 0:
				frappe.db.set_value("Stock Entry", entry.name, "pick_list", None, update_modified=False)
		if self.get("custom_warehouse_transfer"):
			frappe.db.set_value("Pick List", self.name, "custom_warehouse_transfer", None, update_modified=False)
		unlink_cancelled_pick_list(self.name)
		# Only draft transfers are safe to detach. Preserve the transfer items.
		frappe.db.sql("""
			UPDATE `tabWarehouse Transfer Details` d
			INNER JOIN `tabWarehouse Transfer` wt ON wt.name = d.parent
			SET d.against_pick_list = NULL, d.pick_list_item = NULL
			WHERE d.against_pick_list = %s AND wt.docstatus = 0
		""", self.name)


def get_location_balances(item_code, warehouse, batch_no=None):
	"""Read physical-location balances, including counts and completed allocations.

	A Stock Ledger Entry may have no location for warehouse-level transfers and
	receipts, so SLE-only picking misses valid physical locations.
	"""
	from qcmc_logic.api.stock_reconciliation import _current_inventory_quantity

	params = {"item": item_code, "warehouse": warehouse}
	candidates = frappe.db.sql("""
		select distinct locations.location from (
			select sle.location
			from `tabStock Ledger Entry` sle
			where sle.item_code = %(item)s and sle.warehouse = %(warehouse)s
				and sle.is_cancelled = 0 and ifnull(sle.location, '') != ''
			union
			select wal.actual_location as location
			from `tabWarehouse Allocation Location` wal
			inner join `tabStorage Allocation` wa on wa.name = wal.parent
			where wa.docstatus = 1 and wa.status = 'Completed'
				and wal.status = 'VERIFIED' and wal.item_code = %(item)s
				and wa.warehouse = %(warehouse)s
			union
			select coalesce(nullif(pcr.location, ''), pcr.inventory_location) as location
			from `tabQCMC Physical Count Result` pcr
			inner join `tabStock Reconciliation` sr on sr.name = pcr.parent
			where sr.docstatus = 1 and sr.custom_physical_count = 1
				and pcr.item_code = %(item)s and pcr.warehouse = %(warehouse)s
				and ifnull(pcr.status, '') != 'Old Count'
			union
			select lt.target_location as location from `tabLocation Transfer` lt
			where lt.docstatus = 1 and lt.item_code = %(item)s and lt.warehouse = %(warehouse)s
			union
			select lt.source_location as location from `tabLocation Transfer` lt
			where lt.docstatus = 1 and lt.item_code = %(item)s and lt.warehouse = %(warehouse)s
		) locations
		inner join `tabStorage Location` sl on sl.name = locations.location
		where sl.disabled = 0 and sl.is_group = 0
			and sl.custom_warehouse = %(warehouse)s
		order by locations.location
	""", params, as_dict=True)
	result = []
	for candidate in candidates:
		qty = flt(_current_inventory_quantity(
			item_code, warehouse, candidate.location, batch_no=batch_no,
		))
		if qty > 0.000000001:
			result.append(frappe._dict(location=candidate.location, available_qty=qty))
	return result


def get_picking_location_priorities(company, item_code, warehouse, dimensions=None):
	"""Use Putaway Rule picking order, without applying receiving capacity limits.

	Only locations containing available stock can be picked. Item-specific rules
	take precedence over unrestricted rules; unmatched locations are a fallback.
	"""
	from qcmc_logic.overrides.putaway_rule_dimension import (
		get_rule_dimension_fields,
		get_rule_dimension_values,
	)

	meta = frappe.get_meta("Putaway Rule")
	fields = ["name", "location", "item_code", "priority"]
	if meta.has_field("custom_no_item_restriction"):
		fields.append("custom_no_item_restriction")
	fields.extend(field for field in get_rule_dimension_fields() if field not in fields)
	filters = {"company": company, "warehouse": warehouse, "disable": 0}
	rules = frappe.get_all("Putaway Rule", filters=filters, fields=fields,
		order_by="priority asc, creation asc, name asc")
	ranks = {}
	for rule in rules:
		location = rule.get("location")
		if not location:
			continue
		if rule.get("item_code") != item_code and not rule.get("custom_no_item_restriction"):
			continue
		rule_dimensions = get_rule_dimension_values(rule)
		if any(value != (dimensions or {}).get(fieldname)
			for fieldname, value in rule_dimensions.items() if fieldname != "location"):
			continue
		rank = (0 if rule.get("item_code") == item_code else 1,
			flt(rule.get("priority")), rule.name)
		if location not in ranks or rank < ranks[location]:
			ranks[location] = rank
	return ranks


def assign_storage_locations(doc):
	"""Suggest OUT locations using Putaway Rule order and actual positive stock.

	Keep explicit selections untouched, and never allocate more than the live
	item/location balance across multiple rows in the same Pick List.
	"""
	balances = {}
	allocated_rows = []
	for source in list(doc.get("locations") or []):
		row = frappe._dict(copy.deepcopy(source.as_dict()))
		key = (row.item_code, row.warehouse, row.batch_no or "")
		if key not in balances:
			priorities = get_picking_location_priorities(
				doc.company, row.item_code, row.warehouse,
				{field: row.get(field) for field in get_inventory_dimension_fieldnames()
					if field != "location" and row.get(field)},
			)
			balances[key] = sorted(get_location_balances(*key),
				key=lambda balance: (
					0 if balance.location in priorities else 1,
					priorities.get(balance.location, (2, float("inf"), "")),
					balance.location,
				))

		remaining = flt(row.stock_qty)
		remaining_picked = flt(row.picked_qty)
		if row.get("location"):
			for balance in balances[key]:
				if balance.location == row.location:
					balance.available_qty = max(flt(balance.available_qty) - remaining, 0)
					break
			allocated_rows.append(row)
			continue
		if remaining <= 0:
			allocated_rows.append(row)
			continue

		for balance in balances[key]:
			available = flt(balance.available_qty)
			if available <= 0 or remaining <= 0:
				continue
			stock_qty = min(remaining, available)
			allocated = frappe._dict(copy.deepcopy(row))
			allocated.update(
				name=None,
				idx=None,
				location=balance.location,
				stock_qty=stock_qty,
				qty=stock_qty / (flt(row.conversion_factor) or 1),
				picked_qty=min(remaining_picked, stock_qty),
			)
			allocated_rows.append(allocated)
			balance.available_qty = available - stock_qty
			remaining -= stock_qty
			remaining_picked = max(remaining_picked - stock_qty, 0)

		if remaining > 1e-9:
			unallocated = frappe._dict(copy.deepcopy(row))
			unallocated.update(
				name=None,
				idx=None,
				location=None,
				stock_qty=remaining,
				qty=remaining / (flt(row.conversion_factor) or 1),
				picked_qty=remaining_picked,
			)
			allocated_rows.append(unallocated)

	doc.set("locations", [])
	for row in allocated_rows:
		for fieldname in ("name", "parent", "parenttype", "parentfield", "idx"):
			row.pop(fieldname, None)
		doc.append("locations", row)


@frappe.whitelist()
def get_linked_pick_lists(warehouse_transfer):
	"""Read linked Pick Lists from existing item-level references."""
	transfer = frappe.get_doc("Warehouse Transfer", warehouse_transfer)
	transfer.check_permission("read")
	names = sorted({row.against_pick_list for row in transfer.transfer_items
		if row.get("against_pick_list")})
	result = []
	for name in names:
		if not frappe.db.exists("Pick List", {"name": name, "docstatus": ["!=", 2]}):
			continue
		if not frappe.has_permission("Pick List", "read", name):
			continue
		result.append(frappe.db.get_value("Pick List", name,
			["name", "status", "docstatus", "purpose"], as_dict=True))
	return result


@frappe.whitelist()
def get_linked_warehouse_transfers(pick_list):
	"""Reverse lookup via Warehouse Transfer Details, honoring permissions."""
	pick = frappe.get_doc("Pick List", pick_list)
	pick.check_permission("read")
	if pick.docstatus == 2:
		return []
	names = frappe.db.get_all("Warehouse Transfer Details",
		filters={"against_pick_list": pick_list}, pluck="parent")
	result = []
	for name in sorted(set(names)):
		if not frappe.db.exists("Warehouse Transfer", name):
			continue
		if not frappe.has_permission("Warehouse Transfer", "read", name):
			continue
		result.append(frappe.db.get_value("Warehouse Transfer", name,
			["name", "transfer_status", "docstatus"], as_dict=True))
	return result


@frappe.whitelist(methods=["POST"])
def create_pick_list_from_warehouse_transfer(warehouse_transfer):
	"""Create and link a draft Pick List to a draft same-company Warehouse Transfer.

	One source Pick List Item is retained for each transfer item to keep the
	existing pick_list_item foreign key accurate. Locations can be reviewed
	and assigned on the Pick List before submission.
	"""
	transfer = frappe.get_doc("Warehouse Transfer", warehouse_transfer)
	transfer.check_permission("write")
	frappe.has_permission("Pick List", "create", throw=True)
	if transfer.docstatus != 0 or transfer.transfer_status != "Draft":
		frappe.throw(_("Only draft Warehouse Transfers can create a Pick List."))
	if transfer.transfer_type != "Warehouse Transfer":
		frappe.throw(_("This action currently supports Warehouse Transfer only."))
	if not transfer.source_warehouse or not transfer.target_warehouse:
		frappe.throw(_("Source and Target Warehouses are required."))
	company = frappe.db.get_value("Warehouse", transfer.source_warehouse, "company")
	if not company or company != frappe.db.get_value("Warehouse", transfer.target_warehouse, "company"):
		frappe.throw(_("Both warehouses must belong to the same company."))

	items = [item for item in transfer.get("transfer_items") or [] if flt(item.issued_qty) > 0]
	if not items:
		frappe.throw(_("Add items with positive Issued Qty first."))
	# Repair links left by Pick Lists cancelled before the unlink hook existed.
	# The Warehouse Transfer is guaranteed to be a draft here.
	for item in transfer.transfer_items:
		if item.against_pick_list and not frappe.db.exists("Pick List", {
			"name": item.against_pick_list, "docstatus": ["!=", 2],
		}):
			frappe.db.set_value("Warehouse Transfer Details", item.name,
				{"against_pick_list": None, "pick_list_item": None}, update_modified=False)
			item.against_pick_list = None
			item.pick_list_item = None
	existing = {item.against_pick_list for item in transfer.transfer_items if item.against_pick_list}
	if existing:
		if len(existing) == 1 and frappe.db.exists("Pick List", next(iter(existing))):
			return {"name": next(iter(existing)), "existing": True}
		frappe.throw(_("This Warehouse Transfer already has Pick List references. Review them first."))

	pick_list = frappe.new_doc("Pick List")
	pick_list.company = company
	pick_list.purpose = "Warehouse Transfer"
	pick_list.custom_warehouse_transfer = transfer.name
	pick_list.parent_warehouse = transfer.source_warehouse
	# Keep stable one-to-one child references on the transfer.
	pick_list.pick_manually = 1
	for item in items:
		stock_uom = frappe.get_cached_value("Item", item.item_code, "stock_uom")
		if not stock_uom:
			frappe.throw(_("Item {0} has no Stock UOM.").format(item.item_code))
		from erpnext.stock.get_item_details import get_conversion_factor
		factor = 1 if item.uom == stock_uom else flt(
			get_conversion_factor(item.item_code, item.uom).get("conversion_factor"))
		if factor <= 0:
			frappe.throw(_("Invalid conversion factor for Item {0}.").format(item.item_code))
		stock_qty = flt(item.issued_qty) * factor
		row = pick_list.append("locations", {
			"item_code": item.item_code,
			"warehouse": transfer.source_warehouse,
			"uom": item.uom or stock_uom,
			"stock_uom": stock_uom,
			"conversion_factor": factor,
			"qty": flt(item.issued_qty),
			"stock_qty": stock_qty,
			"picked_qty": 0,
			"material_request": item.material_request,
			"material_request_item": item.material_request_item,
		})
		# Assign inventory dimensions only when the Pick List row supports them.
		copy_inventory_dimensions(item, row)

	pick_list.insert()
	for transfer_item, pick_item in zip(items, pick_list.locations):
		frappe.db.set_value("Warehouse Transfer Details", transfer_item.name, {
			"against_pick_list": pick_list.name,
			"pick_list_item": pick_item.name,
		}, update_modified=False)
	return {"name": pick_list.name, "existing": False}


@frappe.whitelist()
def suggest_pick_locations(pick_list):
	"""Preview rule-prioritized OUT picking locations without saving stock data."""
	data = json.loads(pick_list) if isinstance(pick_list, str) else pick_list
	doc = frappe.get_doc(data)
	doc.check_permission("write")
	if doc.docstatus != 0:
		frappe.throw(_("Only draft Pick Lists can have locations suggested."))
	if not doc.company:
		frappe.throw(_("Select a Company first."))
	if not doc.get("locations"):
		frappe.throw(_("Add Pick List items before suggesting locations."))
	assign_storage_locations(doc)
	return [row.as_dict() for row in doc.locations]


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
	if pick_list.purpose not in ("Material Transfer", "Warehouse Transfer"):
		frappe.throw(_("Warehouse Transfer can only be created for Warehouse Transfer Pick Lists."))
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
		if source.get(fieldname) and _dimension_field_matches(source.doctype, target.doctype, fieldname):
			target.set(fieldname, source.get(fieldname))


def _dimension_field_matches(source_doctype, target_doctype, fieldname):
	source_field = frappe.get_meta(source_doctype).get_field(fieldname)
	target_field = frappe.get_meta(target_doctype).get_field(fieldname)
	if not source_field or not target_field:
		return False
	if source_field.fieldtype != target_field.fieldtype:
		return False
	if source_field.fieldtype == "Link" and source_field.options != target_field.options:
		return False
	return True


def get_inventory_dimension_fieldnames():
	if not frappe.db.exists("DocType", "Inventory Dimension"):
		return []

	filters = (
		{"disabled": 0}
		if frappe.get_meta("Inventory Dimension").has_field("disabled")
		else None
	)
	return frappe.get_all(
		"Inventory Dimension",
		filters=filters,
		pluck="source_fieldname",
	)


@frappe.whitelist()
def create_stock_entry(pick_list):
	pick_list_doc = frappe.get_doc(json.loads(pick_list))
	stock_entry = erpnext_create_stock_entry(pick_list)
	if not stock_entry:
		return stock_entry

	stock_entry = frappe._dict(stock_entry)
	if pick_list_doc.get("custom_job_card"):
		stock_entry.job_card = pick_list_doc.custom_job_card
	for source, target in zip(pick_list_doc.get("locations") or [], stock_entry.get("items") or []):
		if source.get("custom_job_card_item"):
			target["job_card_item"] = source.custom_job_card_item
		for fieldname in get_inventory_dimension_fieldnames():
			if source.get(fieldname):
				target[fieldname] = source.get(fieldname)
	return stock_entry


def validate_pick_list_references(doc):
	"""Validate against live submitted Pick List rows, not stale child IDs.

	Putaway-based picking can split one source row into several location rows,
	which deletes the original child name. The Pick List itself is the stable
	reference. Totals are checked per item and Material Request reference.
	"""
	requested = {}
	for row in doc.get("transfer_items") or []:
		if not row.get("against_pick_list"):
			if row.get("pick_list_item"):
				frappe.throw(_("Row {0}: Pick List Item requires a Pick List reference.").format(row.idx))
			continue
		name = row.against_pick_list
		pick_list = frappe.db.get_value("Pick List", name, ["docstatus", "company"], as_dict=True)
		if not pick_list or pick_list.docstatus != 1:
			frappe.throw(_("Row {0}: Linked Pick List {1} must be submitted and active.").format(row.idx, name))
		if pick_list.company != doc.source_company:
			frappe.throw(_("Row {0}: Linked Pick List company does not match.").format(row.idx))
		key = (name, row.item_code, row.get("material_request_item") or "")
		requested[key] = requested.get(key, 0) + flt(row.issued_qty)
		rows = frappe.db.get_all("Pick List Item",
			filters={"parent": name, "item_code": row.item_code, "warehouse": doc.source_warehouse},
			fields=["name", "picked_qty", "delivered_qty", "material_request_item"],
			order_by="idx asc")
		rows = [item for item in rows if (item.material_request_item or "") == key[2]]
		if not rows:
			frappe.throw(_("Row {0}: No matching item and source warehouse exist on Pick List {1}.").format(row.idx, name))
		# Repair the child pointer only when exactly one live row matches.
		# Split locations are represented by the stable Pick List reference.
		row.pick_list_item = rows[0].name if len(rows) == 1 else None

	for (name, item_code, request_item), qty in requested.items():
		rows = frappe.db.get_all("Pick List Item",
			filters={"parent": name, "item_code": item_code, "warehouse": doc.source_warehouse},
			fields=["picked_qty", "delivered_qty", "material_request_item"])
		pending = sum(max(flt(r.picked_qty) - flt(r.delivered_qty), 0)
			for r in rows if (r.material_request_item or "") == request_item)
		if qty > pending + 1e-6:
			frappe.throw(_("Issued Qty for Item {0} exceeds pending picked quantity on Pick List {1} ({2}).").format(
				item_code, name, pending))


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
	"""Distribute issued quantities over current Pick List rows.

	Pick List locations may be split/recreated after Warehouse Transfer rows
	were first linked; never rely exclusively on outdated child row names.
	"""
	picked = frappe.db.get_all("Pick List Item", filters={"parent": pick_list_name},
		fields=["name", "item_code", "material_request_item", "warehouse", "picked_qty"],
		order_by="idx asc")
	issued = frappe.db.sql("""
		select wtd.item_code, wtd.material_request_item, wt.source_warehouse,
			sum(wtd.issued_qty) as issued_qty
		from `tabWarehouse Transfer Details` wtd
		inner join `tabWarehouse Transfer` wt on wt.name = wtd.parent
		where wt.docstatus = 1
		  and wt.transfer_status in ('Transferred', 'Received')
		  and wtd.against_pick_list = %s
		group by wtd.item_code, wtd.material_request_item, wt.source_warehouse
	""", pick_list_name, as_dict=True)
	remaining = {
		(row.item_code, row.material_request_item or "", row.source_warehouse): flt(row.issued_qty)
		for row in issued
	}
	for row in picked:
		key = (row.item_code, row.material_request_item or "", row.warehouse)
		delivered = min(max(remaining.get(key, 0), 0), flt(row.picked_qty))
		remaining[key] = max(remaining.get(key, 0) - delivered, 0)
		frappe.db.set_value("Pick List Item", row.name, "delivered_qty",
			delivered, update_modified=False)


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
