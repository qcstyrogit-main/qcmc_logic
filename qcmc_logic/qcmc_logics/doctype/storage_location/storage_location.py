import json
import re

import frappe
from frappe import _
from frappe.utils import flt
from frappe.utils.nestedset import NestedSet

from qcmc_logic.overrides.putaway_rule_dimension import (
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
	"""Return positive stock balances for one exact leaf Storage Location."""
	from qcmc_logic.utils import check_warehouse_access

	storage_location = str(storage_location or "").strip()
	if not storage_location:
		frappe.throw(_("Storage Location is required."))
	location = frappe.db.get_value(
		"Storage Location",
		storage_location,
		["name", "location_code", "location_name", "custom_warehouse", "is_group", "disabled"],
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

	rows = frappe.db.sql(
		"""
		select
			sle.item_code,
			coalesce(item.item_name, sle.item_code) as item_name,
			coalesce(item.stock_uom, '') as uom,
			coalesce(sle.batch_no, '') as batch_no,
			sum(sle.actual_qty) as actual_qty,
			max(concat(sle.posting_date, ' ', sle.posting_time)) as last_movement
		from `tabStock Ledger Entry` sle
		left join `tabItem` item on item.name = sle.item_code
		where sle.is_cancelled = 0
			and sle.warehouse = %(warehouse)s
			and sle.location = %(location)s
		group by sle.item_code, item.item_name, item.stock_uom, coalesce(sle.batch_no, '')
		having sum(sle.actual_qty) > 0
		order by item.item_name, sle.item_code, batch_no
		""",
		{"warehouse": location.custom_warehouse, "location": location.name},
		as_dict=True,
	)
	for row in rows:
		row.actual_qty = flt(row.actual_qty)

	return {
		"storage_location": location.name,
		"location_code": location.location_code,
		"location_name": location.location_name,
		"warehouse": location.custom_warehouse,
		"item_count": len({row.item_code for row in rows}),
		"balances": rows,
	}


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
				"item_code": rule.item_code,
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
