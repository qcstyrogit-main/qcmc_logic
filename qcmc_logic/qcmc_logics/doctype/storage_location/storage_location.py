import json
import re

import frappe
from frappe import _
from frappe.utils import flt
from frappe.utils.nestedset import NestedSet

from qcmc_logic.overrides.putaway_rule_dimension import (
	get_location_total_physical_balance,
	get_ordered_dimension_putaway_rules,
)


def normalize_location_code(value):
	return re.sub(
		r"[^A-Z0-9_-]+",
		"-",
		str(value or "").strip().upper(),
	).strip("-")


def natural_location_sort_key(value):
	"""Sort human numbered names as 1, 2, ... 10 instead of 1, 10, 2."""
	return tuple(
		int(part) if part.isdigit() else part.casefold()
		for part in re.split(r"(\d+)", str(value or ""))
	)


class StorageLocation(NestedSet):
	nsm_parent_field = "parent_storage_location"

	def autoname(self):
		code = normalize_location_code(self.location_code)

		if not code:
			frappe.throw(_("Location Code is required."))

		self.location_code = code
		self.name = code

	def before_rename(self, old, new, merge=False):
		if merge:
			frappe.throw(_("Storage Locations cannot be merged."))
		code = normalize_location_code(new)
		if not code:
			frappe.throw(_("Location Code is required."))
		return code

	def after_rename(self, old, new, merge=False):
		# Keep the canonical document ID and Location Code identical even when
		# renamed from the standard tree action or another Frappe API.
		frappe.db.set_value(
			"Storage Location", new, "location_code", new, update_modified=False
		)
		refresh_storage_location_paths()
		refresh_storage_location_qr_payloads()

	def validate(self):
		self._validate_location_name()
		self._validate_parent()
		self._set_qr_payload()

	def _validate_location_name(self):
		self.location_name = (self.location_name or "").strip()

		if not self.location_name:
			frappe.throw(_("Location Name is required."))

	def _validate_parent(self):
		if not self.parent_storage_location:
			self.full_path = self.location_name
			return

		parent = frappe.db.get_value(
			"Storage Location",
			self.parent_storage_location,
			["full_path", "location_name", "disabled", "is_group"],
			as_dict=True,
		)

		if not parent:
			frappe.throw(_("Parent Storage Location does not exist."))

		if parent.disabled:
			frappe.throw(_("Parent Storage Location is disabled."))

		if not parent.is_group:
			frappe.throw(
				_(
					"Parent Storage Location {0} must be a group."
				).format(self.parent_storage_location)
			)

		parent_path = (
			parent.full_path
			or self.parent_storage_location
		)

		segment = _relative_path_segment(self.location_name, parent.location_name)
		self.full_path = f"{parent_path} / {segment}"

	def _set_qr_payload(self):
		# Keep the encoded QR intentionally compact. Descriptive data remains on
		# the printed label and is resolved authoritatively from ERP by location_id.
		self.qr_payload = json.dumps(
			{
				"type": "storage_location",
				"location_id": self.name,
				"warehouse": self.get("custom_warehouse") or "",
			},
			separators=(",", ":"),
		)


def refresh_storage_location_qr_payloads(storage_location=None):
	"""Regenerate persisted payloads after canonical identity changes."""
	names = [storage_location] if storage_location else frappe.get_all(
		"Storage Location", pluck="name"
	)
	refreshed = []
	for name in names:
		doc = frappe.get_doc("Storage Location", name)
		doc._set_qr_payload()
		frappe.db.set_value(
			"Storage Location", doc.name, "qr_payload", doc.qr_payload,
			update_modified=False,
		)
		refreshed.append({"name": doc.name, "payload": json.loads(doc.qr_payload)})
	return refreshed


def _relative_path_segment(location_name, parent_location_name=None):
	"""Remove a repeated parent name from one hierarchy path segment."""
	segment = str(location_name or "").strip()
	parent_name = str(parent_location_name or "").strip()
	if not segment or not parent_name:
		return segment

	match = re.match(
		rf"^{re.escape(parent_name)}(?:\s+|\s*[/\-]\s*)",
		segment,
		flags=re.IGNORECASE,
	)
	if match:
		shortened = segment[match.end():].strip()
		if shortened:
			return shortened

	# Some children repeat only the building portion of a longer parent name,
	# e.g. parent "... GROUND FLOOR" and child "... STAGING AREA".
	segment_words = segment.split()
	parent_words = parent_name.split()
	common_words = 0
	for segment_word, parent_word in zip(segment_words, parent_words):
		if segment_word.casefold() != parent_word.casefold():
			break
		common_words += 1
	if common_words >= 2 and common_words < len(segment_words):
		return " ".join(segment_words[common_words:])
	return segment


def refresh_storage_location_paths():
	"""Rebuild all stored paths from concise relative hierarchy segments."""
	rows = frappe.get_all(
		"Storage Location",
		fields=["name", "location_name", "parent_storage_location", "lft"],
		order_by="lft asc",
		limit_page_length=0,
	)
	by_name = {}
	refreshed = []
	for row in rows:
		parent = by_name.get(row.parent_storage_location)
		if parent:
			segment = _relative_path_segment(row.location_name, parent.location_name)
			full_path = f"{parent.full_path} / {segment}"
		else:
			full_path = str(row.location_name or row.name).strip()

		row.full_path = full_path
		by_name[row.name] = row
		frappe.db.set_value(
			"Storage Location", row.name, "full_path", full_path, update_modified=False
		)
		refreshed.append({"name": row.name, "full_path": full_path})
	return refreshed


@frappe.whitelist()
def rename_storage_location(storage_location, location_code, location_name):
	"""Rename the canonical code and display name in one atomic operation."""
	from frappe.model.rename_doc import rename_doc

	if not frappe.has_permission("Storage Location", "write", doc=storage_location):
		frappe.throw(_("You do not have permission to rename this Storage Location."), frappe.PermissionError)

	if not frappe.db.exists("Storage Location", storage_location):
		frappe.throw(_("Storage Location {0} does not exist.").format(storage_location))

	new_code = normalize_location_code(location_code)
	new_name = str(location_name or "").strip()
	if not new_code:
		frappe.throw(_("Location Code is required."))
	if not new_name:
		frappe.throw(_("Location Name is required."))

	if new_code != storage_location:
		new_code = rename_doc("Storage Location", storage_location, new_code)

	doc = frappe.get_doc("Storage Location", new_code)
	doc.location_code = new_code
	doc.location_name = new_name
	doc.save()
	refresh_storage_location_paths()
	refresh_storage_location_qr_payloads()

	return {
		"name": doc.name,
		"location_code": doc.location_code,
		"location_name": doc.location_name,
		"full_path": frappe.db.get_value("Storage Location", doc.name, "full_path"),
	}


@frappe.whitelist()
def update_storage_location_from_tree(
	storage_location,
	location_code,
	location_name,
	location_type,
	custom_warehouse,
	is_group=0,
):
	"""Update the editable tree fields while preserving canonical location codes."""
	from frappe.model.rename_doc import rename_doc

	if not frappe.has_permission("Storage Location", "write", doc=storage_location):
		frappe.throw(
			_("You do not have permission to update this Storage Location."),
			frappe.PermissionError,
		)
	if not frappe.db.exists("Storage Location", storage_location):
		frappe.throw(_("Storage Location {0} does not exist.").format(storage_location))

	new_code = normalize_location_code(location_code)
	if not new_code:
		frappe.throw(_("Location Code is required."))
	if new_code != storage_location:
		new_code = rename_doc("Storage Location", storage_location, new_code)

	doc = frappe.get_doc("Storage Location", new_code)
	doc.location_code = new_code
	doc.location_name = str(location_name or "").strip()
	doc.location_type = location_type
	doc.custom_warehouse = custom_warehouse
	doc.is_group = frappe.sbool(is_group)
	doc.save()
	refresh_storage_location_paths()
	refresh_storage_location_qr_payloads()

	return {
		"name": doc.name,
		"location_code": doc.location_code,
		"location_name": doc.location_name,
	}


@frappe.whitelist()
def get_storage_location_tree_nodes(doctype=None, parent="", include_disabled=False, **filters):
	"""Return tree children using natural numeric Location Name ordering."""
	if not frappe.has_permission("Storage Location", "read"):
		frappe.throw(_("You do not have permission to view Storage Locations."), frappe.PermissionError)

	if isinstance(include_disabled, str):
		include_disabled = frappe.sbool(include_disabled)
	db_filters = {"parent_storage_location": parent or ["is", "not set"]}
	if not include_disabled:
		db_filters["disabled"] = 0

	rows = frappe.get_all(
		"Storage Location",
		filters=db_filters,
		fields=["name as value", "location_name as title", "is_group as expandable"],
		limit_page_length=0,
	)
	return sorted(
		rows,
		key=lambda row: (
			natural_location_sort_key(row.title),
			natural_location_sort_key(row.value),
		),
	)


@frappe.whitelist()
def get_storage_location_item_balances(storage_location):
	"""Return completed Warehouse Allocation balances for one leaf location."""
	from qcmc_logic.utils import check_warehouse_access

	storage_location = str(storage_location or "").strip()
	if not storage_location:
		frappe.throw(_("Storage Location is required."))
	location = frappe.db.get_value(
		"Storage Location",
		storage_location,
		_get_storage_location_balance_fields(),
		as_dict=True,
	)
	if not location or location.disabled:
		frappe.throw(_("Storage Location {0} does not exist or is disabled.").format(storage_location))
	if not frappe.has_permission("Storage Location", "read", doc=location.name):
		frappe.throw(_("You do not have permission to view this Storage Location."), frappe.PermissionError)
	if location.is_group:
		frappe.throw(_("Select a leaf Storage Location to view exact item balances."))
	if not location.custom_warehouse:
		frappe.throw(_("Storage Location {0} has no Warehouse.").format(location.name))
	if not check_warehouse_access(frappe.session.user, location.custom_warehouse):
		frappe.throw(
			_("You do not have access to Warehouse {0}.").format(location.custom_warehouse),
			frappe.PermissionError,
		)

	rows = _get_warehouse_allocation_location_balances(
		location.name,
		location.custom_warehouse,
	)
	from qcmc_logic.api.stock_reconciliation import _current_inventory_quantity
	for row in rows:
		row.actual_qty = _current_inventory_quantity(
			row.item_code, location.custom_warehouse, location.name, row.batch_no or None,
		)
	rows = [row for row in rows if flt(row.actual_qty) > 0.000000001]
	details = _get_warehouse_allocation_location_details(
		location.name,
		location.custom_warehouse,
	)
	movements = _get_location_movement_details(location.name, location.custom_warehouse)
	for row in rows:
		row.actual_qty = flt(row.actual_qty)
	for row in details:
		row.actual_qty = flt(row.actual_qty)
	for row in movements:
		row.quantity = flt(row.quantity)
	capacity_summary = _get_storage_location_capacity_summary(location, rows)

	return {
		"storage_location": location.name,
		"location_code": location.location_code,
		"location_name": location.location_name,
		"warehouse": location.custom_warehouse,
		"item_count": len({row.item_code for row in rows}),
		"balance_source": "Warehouse Allocation + Location Transfer",
		"capacity_summary": capacity_summary,
		"balances": rows,
		"allocation_details": details,
		"movement_details": movements,
	}


def _get_storage_location_balance_fields():
	fields = [
		"name",
		"location_code",
		"location_name",
		"custom_warehouse",
		"is_group",
		"disabled",
	]
	meta = frappe.get_meta("Storage Location")
	for fieldname in ("storage_capacity", "custom_storage_capacity"):
		if meta.has_field(fieldname):
			fields.append(fieldname)
	return fields


def _get_storage_location_capacity_summary(location, balances):
	"""Return configured and free capacity for the item-balance popup."""
	warehouse = location.custom_warehouse
	used_capacity = (
		get_location_total_physical_balance(warehouse, location.name)
		if warehouse else sum(flt(row.actual_qty) for row in balances)
	)
	capacity_uom = _get_single_balance_uom(balances)
	capacity = None
	available_capacity = None
	source = ""
	source_name = ""
	no_capacity_restriction = False

	rule = _get_storage_location_capacity_rule(location.name, warehouse)
	if rule:
		source = "Putaway Rule"
		source_name = rule.name
		capacity_uom = capacity_uom or rule.get("stock_uom") or rule.get("uom") or ""
		no_capacity_restriction = bool(rule.get("custom_no_capacity_restriction"))
		if no_capacity_restriction:
			return {
				"capacity": None,
				"used_capacity": flt(used_capacity),
				"available_capacity": None,
				"uom": capacity_uom,
				"source": source,
				"source_name": source_name,
				"no_capacity_restriction": 1,
			}
		capacity = flt(rule.get("stock_capacity") or rule.get("capacity"))

	if not capacity:
		for fieldname in ("storage_capacity", "custom_storage_capacity"):
			if flt(location.get(fieldname)) > 0:
				capacity = flt(location.get(fieldname))
				source = "Storage Location"
				source_name = location.name
				break

	if capacity:
		available_capacity = max(flt(capacity) - flt(used_capacity), 0)

	return {
		"capacity": flt(capacity) if capacity else None,
		"used_capacity": flt(used_capacity),
		"available_capacity": flt(available_capacity) if available_capacity is not None else None,
		"uom": capacity_uom,
		"source": source,
		"source_name": source_name,
		"no_capacity_restriction": 0,
	}


def _get_single_balance_uom(balances):
	uoms = {
		str(row.get("uom") or "").strip()
		for row in balances
		if str(row.get("uom") or "").strip()
	}
	return next(iter(uoms)) if len(uoms) == 1 else ""


def _get_storage_location_capacity_rule(storage_location, warehouse):
	if not warehouse:
		return None

	meta = frappe.get_meta("Putaway Rule")
	if not meta.has_field("location"):
		return None

	fields = ["name", "capacity", "stock_capacity", "priority"]
	for fieldname in (
		"custom_no_item_restriction",
		"custom_no_capacity_restriction",
		"stock_uom",
		"uom",
	):
		if meta.has_field(fieldname):
			fields.append(fieldname)

	rules = frappe.get_all(
		"Putaway Rule",
		fields=fields,
		filters={
			"warehouse": warehouse,
			"location": storage_location,
			"disable": 0,
		},
		limit_page_length=0,
	)
	if not rules:
		return None

	def sort_key(rule):
		return (
			0 if rule.get("custom_no_capacity_restriction") else 1,
			0 if rule.get("custom_no_item_restriction") else 1,
			-flt(rule.get("stock_capacity") or rule.get("capacity")),
			flt(rule.get("priority")),
			rule.name,
		)

	return sorted(rules, key=sort_key)[0]


def _get_warehouse_allocation_location_balances(storage_location, warehouse):
	"""Return net physical balance: completed allocations plus location transfers."""
	return frappe.db.sql(
		"""
		select
			movement.item_code,
			coalesce(item.item_name, movement.item_code) as item_name,
			coalesce(nullif(movement.uom, ''), item.stock_uom, '') as uom,
			'' as batch_no,
			sum(movement.quantity) as actual_qty,
			max(movement.movement_time) as last_movement
		from (
			select wal.item_code, wal.stock_uom as uom, wal.actual_qty as quantity,
				coalesce(wa.completed_at, wa.modified) as movement_time
			from `tabWarehouse Allocation Location` wal
			inner join `tabWarehouse Allocation` wa on wa.name = wal.parent
			where wa.docstatus = 1 and wa.status = 'Completed'
				and wa.warehouse = %(warehouse)s and wal.status = 'VERIFIED'
				and wal.actual_location = %(storage_location)s
			union all
			select item_code, uom, quantity, transferred_at
			from `tabLocation Transfer`
			where docstatus = 1 and warehouse = %(warehouse)s
				and target_location = %(storage_location)s
			union all
			select item_code, uom, -quantity, transferred_at
			from `tabLocation Transfer`
			where docstatus = 1 and warehouse = %(warehouse)s
				and source_location = %(storage_location)s
			union all
			select pcr.item_code, pcr.uom, pcr.variance, sr.modified
			from `tabQCMC Physical Count Result` pcr
			inner join `tabStock Reconciliation` sr on sr.name = pcr.parent
			where sr.docstatus = 1 and sr.custom_physical_count = 1
				and coalesce(pcr.status, '') != 'Old Count'
				and not (coalesce(pcr.physical_count, 0) = 0 and coalesce(pcr.variance, 0) = 0)
				and pcr.warehouse = %(warehouse)s
				and coalesce(nullif(pcr.location, ''), pcr.inventory_location) = %(storage_location)s
		) movement
		left join `tabItem` item on item.name = movement.item_code
		group by movement.item_code, item.item_name,
			coalesce(nullif(movement.uom, ''), item.stock_uom, '')
		having sum(movement.quantity) > 0
		order by item.item_name, movement.item_code
		""",
		{"warehouse": warehouse, "storage_location": storage_location},
		as_dict=True,
	)


def _get_warehouse_allocation_location_details(storage_location, warehouse):
	"""Return the completed allocation rows behind a location balance."""
	return frappe.db.sql(
		"""
		select
			wa.name as warehouse_allocation,
			wa.transaction_type,
			wal.item_code,
			coalesce(item.item_name, wal.item_code) as item_name,
			wal.source_document,
			wal.source_row,
			wal.actual_qty,
			coalesce(nullif(wal.stock_uom, ''), item.stock_uom, '') as uom,
			coalesce(nullif(wal.user_full_name, ''), nullif(wal.user, ''), '') as allocated_by,
			coalesce(nullif(wal.scanner_id, ''), nullif(wa.device_id, ''), '') as scanner_id,
			wal.scan_time,
			wa.completed_at
		from `tabWarehouse Allocation Location` wal
		inner join `tabWarehouse Allocation` wa on wa.name = wal.parent
		inner join `tabStock Entry` se
			on se.name = wal.source_document
			and wal.source_doctype = 'Stock Entry'
			and se.docstatus = 1
		left join `tabItem` item on item.name = wal.item_code
		where wa.docstatus = 1
			and wa.status = 'Completed'
			and wa.warehouse = %(warehouse)s
			and wal.status = 'VERIFIED'
			and wal.actual_location = %(storage_location)s
			and wal.actual_qty > 0
		order by coalesce(wal.scan_time, wa.completed_at) desc,
			wa.name desc, wal.idx asc
		""",
		{"warehouse": warehouse, "storage_location": storage_location},
		as_dict=True,
	)


def _get_location_movement_details(storage_location, warehouse):
	"""Return allocations and transfers as one signed, chronological history."""
	return frappe.db.sql(
		"""
		select * from (
			select
				coalesce(wa.completed_at, wa.modified) as movement_time,
				'Warehouse Allocation' as movement_type,
				wa.name as reference_name,
				wal.item_code,
				coalesce(item.item_name, wal.item_code) as item_name,
				wal.actual_qty as quantity,
				coalesce(nullif(wal.stock_uom, ''), item.stock_uom, '') as uom,
				'' as source_location,
				wal.actual_location as target_location,
				coalesce(nullif(wal.user_full_name, ''), nullif(wal.user, ''), '') as performed_by,
				coalesce(nullif(wal.scanner_id, ''), nullif(wa.device_id, ''), '') as device_id,
				null as counted_quantity
			from `tabWarehouse Allocation Location` wal
			inner join `tabWarehouse Allocation` wa on wa.name = wal.parent
			left join `tabItem` item on item.name = wal.item_code
			where wa.docstatus = 1 and wa.status = 'Completed'
				and wa.warehouse = %(warehouse)s and wal.status = 'VERIFIED'
				and wal.actual_location = %(storage_location)s
			union all
			select
				lt.transferred_at, 'Location Transfer', lt.name,
				lt.item_code, coalesce(item.item_name, lt.item_code),
				-lt.quantity, lt.uom, lt.source_location, lt.target_location,
				coalesce(nullif(employee.employee_name, ''), lt.erpnext_user), lt.device_id, null
			from `tabLocation Transfer` lt
			left join `tabItem` item on item.name = lt.item_code
			left join `tabEmployee` employee on employee.name = lt.employee
			where lt.docstatus = 1 and lt.warehouse = %(warehouse)s
				and lt.source_location = %(storage_location)s
			union all
			select
				lt.transferred_at, 'Location Transfer', lt.name,
				lt.item_code, coalesce(item.item_name, lt.item_code),
				lt.quantity, lt.uom, lt.source_location, lt.target_location,
				coalesce(nullif(employee.employee_name, ''), lt.erpnext_user), lt.device_id, null
			from `tabLocation Transfer` lt
			left join `tabItem` item on item.name = lt.item_code
			left join `tabEmployee` employee on employee.name = lt.employee
			where lt.docstatus = 1 and lt.warehouse = %(warehouse)s
				and lt.target_location = %(storage_location)s
			union all
			select
				coalesce(pcr.submitted_at, sr.modified), 'Physical Count', sr.name,
				pcr.item_code, coalesce(item.item_name, pcr.item_code),
				pcr.variance, pcr.uom, '',
				coalesce(nullif(pcr.location, ''), pcr.inventory_location),
				coalesce(nullif(pcr.scanner_full_name, ''), pcr.scanner_user), pcr.device_id,
				pcr.physical_count
			from `tabQCMC Physical Count Result` pcr
			inner join `tabStock Reconciliation` sr on sr.name = pcr.parent
			left join `tabItem` item on item.name = pcr.item_code
			where sr.docstatus = 1 and sr.custom_physical_count = 1
				and coalesce(pcr.status, '') != 'Old Count'
				and not (coalesce(pcr.physical_count, 0) = 0 and coalesce(pcr.variance, 0) = 0)
				and pcr.warehouse = %(warehouse)s
				and coalesce(nullif(pcr.location, ''), pcr.inventory_location) = %(storage_location)s
		) movements
		order by movement_time desc, reference_name desc
		""",
		{"warehouse": warehouse, "storage_location": storage_location},
		as_dict=True,
	)


# ============================================================
# PUT-AWAY DISTRIBUTION
# ============================================================


@frappe.whitelist()
def get_putaway_distribution(
	storage_location,
	item_code,
	quantity,
	company=None,
	warehouse=None,
):
	"""
	Distribute scanned quantity across eligible child
	Storage Locations.

	If the scanned Storage Location is a group, such as an Aisle,
	the quantity is automatically distributed to descendant leaf
	locations where:

		disabled = 0
		is_group = 0
		item = scanned item

	Example:

	AISLE-1
	├── RACK-1 | ITEM-A | Capacity 10,000
	├── RACK-2 | ITEM-A | Capacity 10,000
	├── RACK-3 | ITEM-A | Capacity 10,000
	└── RACK-4 | ITEM-B | Capacity 10,000

	Scanned:
		AISLE-1
		ITEM-A
		30,000

	Result:
		RACK-1 = 10,000
		RACK-2 = 10,000
		RACK-3 = 10,000
	"""

	storage_location = (
		storage_location or ""
	).strip()

	item_code = (
		item_code or ""
	).strip()

	quantity = flt(quantity)

	if not storage_location:
		frappe.throw(
			_("Storage Location is required.")
		)

	if not item_code:
		frappe.throw(
			_("Scanned Item Code is required.")
		)

	if quantity <= 0:
		frappe.throw(
			_("Quantity must be greater than zero.")
		)

	if not frappe.db.exists(
		"Storage Location",
		storage_location,
	):
		frappe.throw(
			_(
				"Storage Location {0} does not exist."
			).format(
				storage_location
			)
		)

	location = frappe.get_doc(
		"Storage Location",
		storage_location,
	)

	if location.disabled:
		frappe.throw(
			_(
				"Storage Location {0} is disabled."
			).format(
				location.name
			)
		)

	location_warehouse = str(location.get("custom_warehouse") or "").strip()
	if warehouse and _normalize_warehouse(warehouse) != _normalize_warehouse(location_warehouse):
		frappe.throw(
			_("Requested warehouse '{0}' does not match Storage Location warehouse '{1}'.\n[PUTAWAY_LOCATION_WAREHOUSE_MISMATCH]").format(
				warehouse, location_warehouse
			)
		)
	warehouse = warehouse or location_warehouse
	if warehouse and not company:
		company = frappe.db.get_value("Warehouse", warehouse, "company")

	return _allocate_using_erpnext_putaway_rules(
		location=location,
		item_code=item_code,
		quantity=quantity,
		company=company,
		warehouse=warehouse,
	)


def _allocate_using_erpnext_putaway_rules(
	location, item_code, quantity, company=None, warehouse=None
):
	"""Allocate scanner quantities using ERPNext Putaway Rules as authority."""
	companies = [company] if company else frappe.get_all(
		"Putaway Rule",
		filters={"item_code": item_code, "disable": 0},
		pluck="company",
		distinct=True,
	)
	rules = []
	at_capacity = False
	for company in companies:
		company_at_capacity, company_rules = get_ordered_dimension_putaway_rules(
			item_code, company
		)
		at_capacity = at_capacity or company_at_capacity
		rules.extend(company_rules or [])
	rules.sort(key=lambda rule: (rule.priority, -flt(rule.free_space)))
	if not rules:
		if at_capacity:
			frappe.throw(
				_("ERPNext Putaway Rules for Item {0} have no remaining capacity.").format(
					item_code
				)
			)
		frappe.throw(
			_("No available ERPNext Putaway Rule exists for Item {0}.").format(item_code)
		)

	# The scanned Storage Location identifies the physical scan point only.
	# ERPNext Putaway Rules are the authority for every destination.
	rule_locations = frappe.get_all(
		"Storage Location",
		filters={
			"name": ["in", [rule.get("location") for rule in rules if rule.get("location")]],
			"disabled": 0,
		},
		fields=[
			"name",
			"lft",
			"rgt",
			"location_code",
			"location_name",
			"location_type",
			"full_path",
			"custom_warehouse",
		],
	)
	locations_by_name = {row.name: row for row in rule_locations}
	eligible_rules = []
	for rule in rules:
		if warehouse and rule.warehouse != warehouse:
			continue
		rule_location = locations_by_name.get(rule.get("location"))
		if not rule_location:
			continue
		if _normalize_warehouse(rule.warehouse) != _normalize_warehouse(rule_location.custom_warehouse):
			frappe.throw(
				_("Putaway Rule warehouse '{0}' does not match Storage Location warehouse '{1}'.\n[PUTAWAY_LOCATION_WAREHOUSE_MISMATCH]").format(
					rule.warehouse, rule_location.custom_warehouse or ""
				)
			)
		if location.is_group:
			if not (
				flt(rule_location.lft) > flt(location.lft)
				and flt(rule_location.rgt) < flt(location.rgt)
			):
				continue
		elif rule_location.name != location.name:
			continue
		eligible_rules.append((rule, rule_location))

	if not eligible_rules:
		message = _("No available ERPNext Putaway Rule exists for Item {0}.").format(item_code)
		if at_capacity:
			message = _(
				"ERPNext Putaway Rules for Item {0} have no remaining capacity."
			).format(item_code)
		frappe.throw(message)

	remaining_quantity = quantity
	allocations = []
	for rule, rule_location in eligible_rules:
		if remaining_quantity <= 0:
			break
		available_capacity = flt(rule.get("free_space"))
		allocation_quantity = min(remaining_quantity, available_capacity)
		if allocation_quantity <= 0:
			continue

		allocations.append(
			{
				"putaway_rule": rule.name,
				"storage_location": rule_location.name,
				"location_code": rule_location.location_code,
					"location_name": rule_location.location_name,
					"location_type": rule_location.location_type,
					"location_path": rule_location.full_path,
					"warehouse": rule.warehouse,
					"item_code": item_code,
					"capacity": flt(rule.stock_capacity),
				"available_capacity": available_capacity,
				"quantity": allocation_quantity,
			}
		)
		remaining_quantity -= allocation_quantity

	if remaining_quantity > 0:
		frappe.throw(
			_(
				"Insufficient ERPNext Putaway Rule capacity for Item {0}. "
				"Requested Quantity: {1}. Available Capacity: {2}. Shortage: {3}."
			).format(
				item_code,
				quantity,
				quantity - remaining_quantity,
				remaining_quantity,
			)
		)

	return {
		"success": True,
		"mode": "putaway_rule",
		"scanned_location": location.name,
		"scanned_item": item_code,
		"warehouse": allocations[0]["warehouse"] if allocations else None,
		"requested_quantity": quantity,
		"distributed_quantity": quantity,
		"remaining_quantity": 0,
		"total_capacity": sum(
			flt(rule.get("free_space")) for rule, _location in eligible_rules
		),
		"allocations": allocations,
	}


def _normalize_warehouse(value):
	return re.sub(r"[\s-]+", "", str(value or "").strip().lower())


def _allocate_single_location(
	location,
	item_code,
	quantity,
):
	"""
	Direct allocation when the scanned location is already
	a leaf Rack/Bin/etc.
	"""

	if not location.item:
		frappe.throw(
			_(
				"Storage Location {0} does not have "
				"an assigned Item."
			).format(
				location.name
			)
		)

	if location.item != item_code:
		frappe.throw(
			_(
				"Scanned Item {0} is not allowed in "
				"Storage Location {1}. "
				"This location is assigned to Item {2}."
			).format(
				item_code,
				location.name,
				location.item,
			)
		)

	capacity = flt(
		location.storage_capacity
	)

	if capacity <= 0:
		frappe.throw(
			_(
				"Storage Location {0} does not have "
				"a valid Storage Capacity."
			).format(
				location.name
			)
		)

	if quantity > capacity:
		frappe.throw(
			_(
				"Quantity {0} exceeds the capacity "
				"of Storage Location {1}. "
				"Maximum Capacity: {2}."
			).format(
				quantity,
				location.name,
				capacity,
			)
		)

	return {
		"success": True,
		"mode": "direct",

		"scanned_location":
			location.name,

		"scanned_item":
			item_code,

		"warehouse":
			location.warehouse,

		"requested_quantity":
			quantity,

		"distributed_quantity":
			quantity,

		"remaining_quantity":
			0,

		"total_capacity":
			capacity,

		"allocations": [
			{
				"storage_location":
					location.name,

				"location_code":
					location.location_code,

				"location_name":
					location.location_name,

				"location_type":
					location.location_type,

				"location_path":
					location.full_path,

				"warehouse":
					location.warehouse,

				"item_code":
					location.item,

				"capacity":
					capacity,

				"quantity":
					quantity,
			}
		],
	}


def _allocate_group_location(
	location,
	item_code,
	quantity,
):
	"""
	Automatically distribute quantity across descendant leaf
	Storage Locations.

	Only locations matching the scanned Item are eligible.
	"""

	locations = frappe.get_all(
		"Storage Location",
		filters={
			"warehouse":
				location.warehouse,

			"disabled":
				0,

			"is_group":
				0,

			# Put-away rule:
			# child Item must equal scanned Item QR.
			"item":
				item_code,

			# Must be underneath the scanned parent.
			"lft":
				[">", location.lft],

			"rgt":
				["<", location.rgt],
		},
		fields=[
			"name",
			"location_code",
			"location_name",
			"location_type",
			"warehouse",
			"full_path",
			"item",
			"storage_capacity",
			"lft",
			"rgt",
		],
		order_by="lft asc",
	)

	if not locations:
		frappe.throw(
			_(
				"No child Storage Location is configured "
				"for scanned Item {0} under {1}."
			).format(
				item_code,
				location.name,
			)
		)

	# --------------------------------------------------------
	# ELIGIBLE LOCATIONS
	# --------------------------------------------------------

	eligible_locations = []

	for row in locations:
		capacity = flt(
			row.storage_capacity
		)

		if capacity <= 0:
			continue

		eligible_locations.append(
			row
		)

	if not eligible_locations:
		frappe.throw(
			_(
				"No child Storage Location with valid "
				"capacity is configured for Item {0} "
				"under {1}."
			).format(
				item_code,
				location.name,
			)
		)

	# --------------------------------------------------------
	# TOTAL CAPACITY
	# --------------------------------------------------------

	total_capacity = sum(
		flt(
			row.storage_capacity
		)
		for row
		in eligible_locations
	)

	if quantity > total_capacity:
		frappe.throw(
			_(
				"Insufficient storage capacity for "
				"scanned Item {0}. "
				"Requested Quantity: {1}. "
				"Available Capacity: {2}. "
				"Shortage: {3}."
			).format(
				item_code,
				quantity,
				total_capacity,
				quantity - total_capacity,
			)
		)

	# --------------------------------------------------------
	# DISTRIBUTE
	# --------------------------------------------------------

	remaining_quantity = (
		quantity
	)

	allocations = []

	for row in eligible_locations:
		if remaining_quantity <= 0:
			break

		capacity = flt(
			row.storage_capacity
		)

		allocation_quantity = min(
			remaining_quantity,
			capacity,
		)

		if allocation_quantity <= 0:
			continue

		allocations.append(
			{
				"storage_location":
					row.name,

				"location_code":
					row.location_code,

				"location_name":
					row.location_name,

				"location_type":
					row.location_type,

				"location_path":
					row.full_path,

				"warehouse":
					row.warehouse,

				"item_code":
					row.item,

				"capacity":
					capacity,

				"quantity":
					allocation_quantity,
			}
		)

		remaining_quantity -= (
			allocation_quantity
		)

	distributed_quantity = (
		quantity -
		remaining_quantity
	)

	return {
		"success": True,
		"mode": "putaway",

		"scanned_location":
			location.name,

		"scanned_item":
			item_code,

		"warehouse":
			location.warehouse,

		"requested_quantity":
			quantity,

		"distributed_quantity":
			distributed_quantity,

		"remaining_quantity":
			remaining_quantity,

		"total_capacity":
			total_capacity,

		"allocations":
			allocations,
	}
