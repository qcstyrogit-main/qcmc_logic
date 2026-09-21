import json
from decimal import Decimal, InvalidOperation

import frappe
from frappe import _
from frappe.utils import flt, now_datetime

from qcmc_logic.api.stock_entry_scanner import ScannerAPIError, _resolve_storage_location
from qcmc_logic.api.stock_reconciliation import (
	_authenticate_request_user,
	_extract_mobile_token,
	_resolve_mobile_token_user,
)
from qcmc_logic.api.warehouse_allocation import _committed_location_quantities
from qcmc_logic.api.warehouse_workflow import (
	WorkflowError, active_employee, begin_request, finish_request, request_uuid,
)
from qcmc_logic.overrides.putaway_rule_dimension import (
	get_available_dimension_putaway_capacity, get_dimension_stock_balance,
)
from qcmc_logic.utils import ensure_scanner_warehouse_access


def _error(code, message, details=None, status=400):
	frappe.local.response["http_status_code"] = status
	return {"success": False, "error_code": code, "message": message, **(details or {})}


def _auth(mobile_token):
	token = _extract_mobile_token(mobile_token)
	if token:
		user = _resolve_mobile_token_user(token)
		if not user:
			raise WorkflowError("WAREHOUSE_PERMISSION_DENIED", "Session expired. Please log in again.", status=403)
		return user

	user = _authenticate_request_user(mobile_token)
	if not user or user == "Guest":
		raise WorkflowError("WAREHOUSE_PERMISSION_DENIED", "Session expired. Please log in again.", status=403)
	return user


def _quantity(value):
	try:
		if value in (None, "") or isinstance(value, bool):
			raise ValueError
		value = Decimal(str(value).replace(",", "").strip())
	except (InvalidOperation, TypeError, ValueError):
		raise WorkflowError("INVALID_QUANTITY", "Quantity must be numeric and greater than zero.")
	if not value.is_finite() or value <= 0:
		raise WorkflowError("INVALID_QUANTITY", "Quantity must be numeric and greater than zero.")
	return value


def _location(location_id, user, transact=False):
	try:
		location = _resolve_storage_location(location_id, require_leaf=True)
	except ScannerAPIError as exc:
		codes = {
			"LOCATION_NOT_FOUND": "LOCATION_NOT_FOUND",
			"LOCATION_DISABLED": "LOCATION_DISABLED",
			"LOCATION_IS_GROUP": "LOCATION_IS_GROUP",
		}
		raise WorkflowError(codes.get(exc.code, "INVALID_DESTINATION_LOCATION"), str(exc), exc.details)
	if not location.custom_warehouse:
		raise WorkflowError("INVALID_DESTINATION_LOCATION", "Storage Location must have a Warehouse.")
	try:
		ensure_scanner_warehouse_access(user, [location.custom_warehouse], require_transact=transact)
	except frappe.PermissionError:
		raise WorkflowError("WAREHOUSE_PERMISSION_DENIED", "Warehouse permission denied.", status=403)
	return location


def _item(item_code):
	item = frappe.db.get_value(
		"Item", item_code,
		["name", "item_name", "disabled", "is_stock_item", "stock_uom", "has_batch_no", "has_serial_no"],
		as_dict=True,
	)
	if not item:
		raise WorkflowError("ITEM_NOT_FOUND", f"Item '{item_code}' was not found.")
	if item.disabled:
		raise WorkflowError("ITEM_DISABLED", f"Item '{item_code}' is disabled.")
	if not item.is_stock_item:
		raise WorkflowError("ITEM_NOT_STOCK_ITEM", f"Item '{item_code}' is not a stock item.")
	return item


def _quantity_precision():
	return frappe.get_precision("Stock Entry Detail", "qty") or 2


def _serial_list(value):
	if value in (None, ""):
		return []
	if isinstance(value, str):
		try:
			decoded = json.loads(value)
			if isinstance(decoded, list):
				value = decoded
			else:
				value = value.replace(",", "\n").splitlines()
		except (TypeError, ValueError):
			value = value.replace(",", "\n").splitlines()
	if not isinstance(value, list):
		raise WorkflowError("INVALID_SERIAL", "serial_nos must be a list.")
	serials = [str(serial).strip() for serial in value if str(serial).strip()]
	if len(serials) != len(set(serials)):
		raise WorkflowError("INVALID_SERIAL", "Duplicate Serial Numbers are not allowed.")
	return serials


def _source_balance(item, warehouse, location, batch_no="", serials=None):
	dimensions = {"location": location.name}
	if serials:
		return sum(
			Decimal(str(get_dimension_stock_balance(
				item.name, warehouse, dimensions, batch_no=batch_no or None, serial_no=serial,
			)))
			for serial in serials
		)
	latest_count = frappe.db.sql("""
		select pcr.physical_count, coalesce(pcr.submitted_at, sr.modified) as counted_at
		from `tabQCMC Physical Count Result` pcr
		inner join `tabStock Reconciliation` sr on sr.name = pcr.parent
		where sr.docstatus = 1 and sr.custom_physical_count = 1
			and pcr.item_code = %s and pcr.warehouse = %s
			and coalesce(nullif(pcr.location, ''), pcr.inventory_location) = %s
		order by coalesce(pcr.submitted_at, sr.modified) desc, pcr.idx desc limit 1
	""", (item.name, warehouse, location.name), as_dict=True)
	cutoff = latest_count[0].counted_at if latest_count else None
	allocation_state = frappe.db.sql("""
		select coalesce(sum(wal.actual_qty), 0) as quantity, count(*) as row_count
		from `tabWarehouse Allocation Location` wal
		inner join `tabWarehouse Allocation` wa on wa.name = wal.parent
		where wa.docstatus = 1 and wa.status = 'Completed'
			and wa.warehouse = %s and wal.item_code = %s
			and wal.actual_location = %s and wal.status = 'VERIFIED'
			and (%s is null or coalesce(wa.completed_at, wa.modified) > %s)
	""", (warehouse, item.name, location.name, cutoff, cutoff), as_dict=True)[0]
	allocated = allocation_state.quantity or 0
	has_stock_entry_link = frappe.get_meta("Location Transfer").has_field("stock_entry")
	legacy_transfer_filter = (
		"and coalesce(stock_entry, '') = ''"
		if has_stock_entry_link else ""
	)
	all_movement = frappe.db.sql("""
		select coalesce(sum(case when target_location = %(location)s then quantity else 0 end), 0)
			- coalesce(sum(case when source_location = %(location)s then quantity else 0 end), 0)
		from `tabLocation Transfer`
		where docstatus = 1 and warehouse = %(warehouse)s and item_code = %(item_code)s
			and (%(cutoff)s is null or transferred_at > %(cutoff)s)
	""", {
		"location": location.name,
		"warehouse": warehouse,
		"item_code": item.name,
		"cutoff": cutoff,
	})[0][0] or 0
	legacy_movement = frappe.db.sql(f"""
		select coalesce(sum(case when target_location = %(location)s then quantity else 0 end), 0)
			- coalesce(sum(case when source_location = %(location)s then quantity else 0 end), 0)
		from `tabLocation Transfer`
		where docstatus = 1 and warehouse = %(warehouse)s and item_code = %(item_code)s
			and (%(cutoff)s is null or transferred_at > %(cutoff)s)
			{legacy_transfer_filter}
	""", {
		"location": location.name,
		"warehouse": warehouse,
		"item_code": item.name,
		"cutoff": cutoff,
	})[0][0] or 0
	if latest_count:
		return Decimal(str(latest_count[0].physical_count or 0)) + Decimal(str(allocated)) + Decimal(str(all_movement))
	if allocation_state.row_count:
		return Decimal(str(allocated)) + Decimal(str(all_movement))
	legacy_balance = get_dimension_stock_balance(
		item.name, warehouse, dimensions, batch_no=batch_no or None,
	)
	return Decimal(str(legacy_balance or 0)) + Decimal(str(legacy_movement))


def _validate_tracking(item, warehouse, source, quantity, batch_no, serials):
	if item.has_batch_no:
		if not batch_no:
			raise WorkflowError("BATCH_REQUIRED", "Batch is required for this Item.")
		if not frappe.db.exists("Batch", {"name": batch_no, "item": item.name, "disabled": 0}):
			raise WorkflowError("INVALID_BATCH", "The Batch is invalid for this Item.")
	elif batch_no:
		raise WorkflowError("INVALID_BATCH", "This Item is not batch-controlled.")

	if item.has_serial_no:
		if not serials:
			raise WorkflowError("SERIAL_REQUIRED", "Serial Numbers are required for this Item.")
		if quantity != quantity.to_integral_value() or len(serials) != int(quantity):
			raise WorkflowError("INVALID_SERIAL", "Serial Number count must equal the transfer quantity.")
		for serial in serials:
			serial_data = frappe.db.get_value(
				"Serial No", serial, ["item_code", "warehouse"], as_dict=True,
			)
			if not serial_data or serial_data.item_code != item.name or serial_data.warehouse != warehouse:
				raise WorkflowError("INVALID_SERIAL", f"Serial Number '{serial}' is not available for this Item and Warehouse.")
	elif serials:
		raise WorkflowError("INVALID_SERIAL", "This Item is not serial-controlled.")


def _destination_capacity(item, company, warehouse, target, quantity):
	restricted = str(target.get("custom_restricted_item") or "").strip()
	if restricted and restricted != item.name:
		raise WorkflowError(
			"INVALID_DESTINATION_LOCATION",
			f"{item.name} is not allowed in target location {target.name}.",
		)
	rule = _putaway_rule_for_location(item.name, company, warehouse, target.name)
	if not rule and _item_has_putaway_location_restriction(item.name, company, warehouse):
		raise WorkflowError(
			"INVALID_DESTINATION_LOCATION",
			f"{item.name} is not allowed in target location {target.name}.",
		)
	if rule:
		available = Decimal(str(get_available_dimension_putaway_capacity(rule, item_code=item.name)))
		reserved = _committed_location_quantities(item.name, warehouse)
		available -= Decimal(str(reserved.get(target.name, 0)))
	else:
		capacity = Decimal(str(target.get("custom_storage_capacity") or target.get("storage_capacity") or 0))
		if capacity <= 0:
			return
		occupied = Decimal(str(get_dimension_stock_balance(item.name, warehouse, {"location": target.name})))
		reserved = Decimal(str(_committed_location_quantities(item.name, warehouse).get(target.name, 0)))
		available = capacity - occupied - reserved
	if quantity > max(available, Decimal("0")):
		remaining = max(available, Decimal("0"))
		raise WorkflowError(
			"DESTINATION_CAPACITY_EXCEEDED",
			f"Target location {target.name} has only {remaining} {item.stock_uom} remaining capacity.",
			{"available_quantity": remaining, "requested_quantity": quantity},
		)


def _putaway_rule_for_location(item_code, company, warehouse, location):
	meta = frappe.get_meta("Putaway Rule")
	has_no_item_field = meta.has_field("custom_no_item_restriction")
	fields = ["name", "item_code", "priority"]
	if has_no_item_field:
		fields.append("custom_no_item_restriction")
	rules = frappe.get_all(
		"Putaway Rule",
		filters={"company": company, "warehouse": warehouse, "location": location, "disable": 0},
		or_filters=[
			{"item_code": item_code},
			{"custom_no_item_restriction": 1},
		] if has_no_item_field else {"item_code": item_code},
		fields=fields,
		order_by="priority asc, creation asc",
	)
	rules = sorted(
		rules,
		key=lambda rule: (
			0 if str(rule.get("item_code") or "").strip() == str(item_code or "").strip() else 1,
			rule.priority or 0,
			rule.name,
		),
	)
	return rules[0].name if rules else ""


def _item_has_putaway_location_restriction(item_code, company, warehouse):
	filters = {
		"company": company,
		"warehouse": warehouse,
		"item_code": item_code,
		"disable": 0,
	}
	if frappe.get_meta("Putaway Rule").has_field("location"):
		filters["location"] = ["!=", ""]
	return bool(frappe.db.exists("Putaway Rule", filters))


def _stock_entry_for_transfer(
	item, source, target, quantity, batch_no, serials, device_id, request_id
):
	company = frappe.db.get_value("Warehouse", source.custom_warehouse, "company")
	doc = frappe.new_doc("Stock Entry")
	doc.purpose = "Material Transfer"
	doc.stock_entry_type = "Material Transfer"
	doc.company = company
	doc.from_warehouse = source.custom_warehouse
	doc.to_warehouse = target.custom_warehouse
	doc.apply_putaway_rule = 0

	row = doc.append("items", {
		"item_code": item.name,
		"item_name": item.item_name,
		"s_warehouse": source.custom_warehouse,
		"t_warehouse": target.custom_warehouse,
		"qty": float(quantity),
		"transfer_qty": float(quantity),
		"uom": item.stock_uom,
		"stock_uom": item.stock_uom,
		"conversion_factor": 1,
		"location": source.name,
		"to_location": target.name,
		"batch_no": batch_no or "",
		"serial_no": "\n".join(serials),
	})
	if row.meta.has_field("custom_location_override_device"):
		row.custom_location_override_device = device_id
	if row.meta.has_field("custom_location_override_timestamp"):
		row.custom_location_override_timestamp = now_datetime()
	if row.meta.has_field("custom_actual_storage_location"):
		row.custom_actual_storage_location = target.name
	if row.meta.has_field("custom_location_overridden"):
		row.custom_location_overridden = 1

	doc.flags.ignore_permissions = True
	doc.insert(ignore_permissions=True)
	doc.submit()
	return doc


def _location_transfer_ledger(
	item, source, target, quantity, batch_no, serials, device_id, request_id, user, employee,
	stock_entry=None,
):
	if frappe.db.exists("Location Transfer", {"request_id": request_id}):
		return frappe.get_doc("Location Transfer", {"request_id": request_id})
	doc = frappe.get_doc({
		"doctype": "Location Transfer",
		"request_id": request_id,
		"stock_entry": stock_entry or "",
		"company": frappe.db.get_value("Warehouse", source.custom_warehouse, "company"),
		"warehouse": source.custom_warehouse,
		"item_code": item.name,
		"item_name": item.item_name,
		"quantity": float(quantity),
		"uom": item.stock_uom,
		"source_location": source.name,
		"target_location": target.name,
		"batch_no": batch_no,
		"serial_nos": "\n".join(serials),
		"employee": employee.name,
		"erpnext_user": user,
		"device_id": device_id,
		"transferred_at": now_datetime(),
	})
	doc.insert(ignore_permissions=True)
	doc.submit()
	return doc


@frappe.whitelist(allow_guest=True)
def get_location_context(location_id, mobile_token=None):
	try:
		user = _auth(mobile_token)
		location = _location(location_id, user)
		return {
			"success": True, "location_id": location.name,
			"location_name": location.inventory_location_name,
			"warehouse": location.custom_warehouse, "is_group": bool(location.is_group),
			"enabled": not bool(location.disabled),
		}
	except WorkflowError as exc:
		return _error(exc.code, str(exc), exc.details, exc.status)


@frappe.whitelist(allow_guest=True)
def get_item_stock(
	item_code=None,
	source_location=None,
	batch_no=None,
	serial_nos=None,
	scan_value=None,
	scanned_barcode=None,
	mobile_token=None,
):
	try:
		user = _auth(mobile_token)
		source = _location(source_location, user)
		item = _item(str(item_code or "").strip())
		serials = _serial_list(serial_nos)
		_validate_tracking(
			item,
			source.custom_warehouse,
			source,
			Decimal(len(serials) or 1),
			str(batch_no or "").strip(),
			serials,
		)
		available = _source_balance(item, source.custom_warehouse, source, str(batch_no or "").strip(), serials)
		return {
			"success": True,
			"item_code": item.name,
			"item_name": item.item_name,
			"stock_uom": item.stock_uom,
			"available_quantity": available,
			"quantity_precision": _quantity_precision(),
			"batch_no": str(batch_no or "").strip(),
			"serial_nos": serials,
			"requires_batch": bool(item.has_batch_no),
			"requires_serial": bool(item.has_serial_no),
			"warehouse": source.custom_warehouse,
			"source_location": source.name,
			# Backward compatibility for older scanner builds.
			"has_batch_no": bool(item.has_batch_no),
			"has_serial_no": bool(item.has_serial_no),
		}
	except WorkflowError as exc:
		return _error(exc.code, str(exc), exc.details, exc.status)


@frappe.whitelist(allow_guest=True)
def create_location_transfer(item_code, source_location, target_location, quantity,
	batch_no=None, serial_nos=None, device_id=None, request_id=None, mobile_token=None):
	savepoint = False
	try:
		user = _auth(mobile_token)
		request_id = request_uuid(request_id)
		quantity = _quantity(quantity)
		serials = _serial_list(serial_nos)
		payload = {
			"item_code": str(item_code or "").strip(), "source_location": str(source_location or "").strip(),
			"target_location": str(target_location or "").strip(), "quantity": quantity,
			"batch_no": str(batch_no or "").strip(), "serial_nos": serials,
			"device_id": str(device_id or "").strip(),
		}
		try:
			request = begin_request("location_transfer.create", request_id, payload, user)
		except WorkflowError as exc:
			if exc.code == "DUPLICATE_TRANSACTION":
				raise WorkflowError("REQUEST_ID_PAYLOAD_MISMATCH", "This request ID has already been used with different transfer details.")
			raise
		if request.replay is not None:
			request.replay["duplicate_request"] = True
			return request.replay

		source = _location(payload["source_location"], user, transact=True)
		target = _location(payload["target_location"], user, transact=True)
		if source.name == target.name:
			raise WorkflowError("SOURCE_TARGET_SAME", "Source and Destination Locations must be different.")
		if source.custom_warehouse != target.custom_warehouse:
			raise WorkflowError("WAREHOUSE_MISMATCH", "Source and Destination Locations must belong to the same Warehouse.")
		item = _item(payload["item_code"])
		_validate_tracking(item, source.custom_warehouse, source, quantity, payload["batch_no"], serials)
		initial_balance = _source_balance(item, source.custom_warehouse, source, payload["batch_no"], serials)
		if initial_balance <= 0:
			raise WorkflowError("ITEM_NOT_IN_SOURCE_LOCATION", "Item has no stock in the Source Location.")
		if quantity > initial_balance:
			raise WorkflowError("INSUFFICIENT_SOURCE_QUANTITY", f"Only {initial_balance} {item.stock_uom} is available in {source.name}.", {
				"available_quantity": initial_balance,
				"latest_available_quantity": initial_balance,
				"requested_quantity": quantity,
			})
		company = frappe.db.get_value("Warehouse", source.custom_warehouse, "company")
		_destination_capacity(item, company, source.custom_warehouse, target, quantity)

		frappe.db.savepoint("location_transfer")
		savepoint = True
		frappe.db.sql("select name from `tabBin` where item_code=%s and warehouse=%s for update", (item.name, source.custom_warehouse))
		current_balance = _source_balance(item, source.custom_warehouse, source, payload["batch_no"], serials)
		if current_balance != initial_balance:
			raise WorkflowError("STOCK_CHANGED", "Stock quantity changed in ERPNext. Please review the latest available quantity.", {
				"available_quantity": current_balance,
				"latest_available_quantity": current_balance,
			})
		if quantity > current_balance:
			raise WorkflowError("INSUFFICIENT_SOURCE_QUANTITY", f"Only {current_balance} {item.stock_uom} is available in {source.name}.", {
				"available_quantity": current_balance,
				"latest_available_quantity": current_balance,
				"requested_quantity": quantity,
			})
		_destination_capacity(item, company, source.custom_warehouse, target, quantity)
		employee = active_employee(user)
		stock_entry = _stock_entry_for_transfer(
			item,
			source,
			target,
			quantity,
			payload["batch_no"],
			serials,
			payload["device_id"],
			request_id,
		)
		location_transfer = _location_transfer_ledger(
			item,
			source,
			target,
			quantity,
			payload["batch_no"],
			serials,
			payload["device_id"],
			request_id,
			user,
			employee,
			stock_entry.name,
		)
		result = {
			"success": True, "request_id": request_id, "duplicate_request": False,
			"stock_entry": stock_entry.name, "docstatus": stock_entry.docstatus, "status": "Submitted",
			"location_transfer": location_transfer.name,
			"completed_reference": stock_entry.name, "reference_doctype": "Stock Entry",
			"warehouse": source.custom_warehouse, "item_code": item.name, "item_name": item.item_name,
			"stock_uom": item.stock_uom, "quantity": quantity,
			"source_location": source.name, "target_location": target.name,
		}
		return finish_request(request, result)
	except WorkflowError as exc:
		if savepoint:
			frappe.db.rollback(save_point="location_transfer")
		return _error(exc.code, str(exc), exc.details, exc.status)
	except Exception:
		if savepoint:
			frappe.db.rollback(save_point="location_transfer")
		frappe.log_error(frappe.get_traceback(), "Location Transfer failed")
		return _error("TRANSFER_FAILED", "Location Transfer could not be completed.")
