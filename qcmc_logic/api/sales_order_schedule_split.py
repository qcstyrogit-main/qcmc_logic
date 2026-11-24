"""Retired Sales Order Item splitting compatibility APIs.

Delivery dates and quantities are owned by SO Delivery Schedule records. These
endpoints remain as explicit rejection responses for old clients; no SO Item is
split, deleted, or rewritten by the delivery scheduling workflow.
"""

import hashlib
import math
from copy import deepcopy
from decimal import Decimal, InvalidOperation

import frappe
from frappe import _
from frappe.utils import flt, getdate, today

from qcmc_logic.api import sales_order_scheduling_service as scheduling


COPY_FIELDS = (
	"item_code", "item_name", "description", "item_group", "brand", "image",
	"warehouse", "uom", "stock_uom", "conversion_factor", "rate", "base_rate",
	"price_list_rate", "base_price_list_rate", "discount_percentage", "discount_amount",
	"distributed_discount_amount", "margin_type", "margin_rate_or_amount", "rate_with_margin",
	"item_tax_template", "item_tax_rate", "cost_center", "project", "income_account",
	"expense_account", "weight_per_unit", "weight_uom", "bom_no", "delivery_date",
	"grant_commission", "is_stock_item", "valuation_rate", "additional_notes", "location",
	"customer_item_code", "base_rate_with_margin", "pricing_rules", "is_free_item",
	"page_break", "transaction_date", "reserve_stock", "stock_uom_rate",
	"custom_customer_history_item_code", "custom_customer_history_rate", "custom_customer_history_rate_selected",
)
COUNTERS = (
	"billed_amt", "produced_qty", "picked_qty", "ordered_qty", "stock_reserved_qty",
	"work_order_qty", "returned_qty", "planned_qty", "production_plan_qty", "requested_qty", "subcontracted_qty",
)
FINANCIAL_FIELDS = (
	"total_qty", "total", "base_total", "net_total", "base_net_total",
	"total_taxes_and_charges", "base_total_taxes_and_charges", "grand_total",
	"base_grand_total", "rounded_total", "base_rounded_total", "rounding_adjustment",
	"base_rounding_adjustment", "discount_amount", "base_discount_amount",
	"advance_paid", "total_commission", "total_contribution",
	"total_net_weight",
)


@frappe.whitelist()
def get_rebalance_dates(source_so_detail):
	so, source = _load_source(source_so_detail)
	validate_schedule_change(so, source)
	_validate_workflow(so)
	fields = _copy_fields(source)
	return [{"date": _schedule_date(row), "qty": row.qty,
		"compatible": _same_context(source, row, fields)}
		for row in so.items if row.name != source.name and row.item_code == source.item_code and row.warehouse == source.warehouse]


@frappe.whitelist()
def preview_split(source_so_detail, quantity=None, delivery_date=None, retained_quantity=None):
	so, source = _load_source(source_so_detail)
	quantity = _resolve_quantity(source, quantity, retained_quantity)
	return _prepare(so, source, quantity, delivery_date)


@frappe.whitelist(methods=["POST"])
def split_schedule(source_so_detail, quantity=None, delivery_date=None, reason=None, expected_state=None, retained_quantity=None):
	if not isinstance(reason, str) or not reason.strip() or len(reason.strip()) > 1000:
		frappe.throw(_("Enter remarks of 1 to 1000 characters."))
	if not expected_state:
		frappe.throw(_("Preview the rebalance before applying it."))
	so, source = _load_source(source_so_detail, lock=True)
	quantity = _resolve_quantity(source, quantity, retained_quantity)
	preview = _prepare(so, source, quantity, delivery_date)
	if preview["state"] != expected_state:
		frappe.throw(_("The order or its allocations changed. Preview the rebalance again."), frappe.TimestampMismatchError)

	# A consumed preview cannot be replayed: its complete document/allocation digest
	# changes under the parent lock. Retry fails safely instead of duplicating a row.
	before = frappe.get_doc(deepcopy(so.as_dict()))
	financials = _financial_snapshot(so)
	existing_names = {row.name for row in so.items}
	values = {field: source.get(field) for field in _copy_fields(source)}
	values.update(qty=preview["move_qty"], delivery_date=preview["new_date"])
	for field in ("delivered_qty", *COUNTERS):
		if source.meta.has_field(field):
			values[field] = 0
	if source.meta.has_field("custom_next_scheduling_date"):
		values["custom_next_scheduling_date"] = None
	savepoint = "schedule_split"
	frappe.db.savepoint(savepoint)
	try:
		mode = preview["mode"]
		if mode == "move":
			# Zero remaining means move the complete row, preserving its identity
			# and avoiding an invalid zero-quantity child on a submitted SO.
			source.delivery_date = preview["new_date"]
			source.custom_next_scheduling_date = None
			destination = source
		else:
			source.qty = preview["retained_qty"]
			if mode == "merge":
				destination = next(row for row in so.items if row.name == preview["target"])
				destination.qty = preview["destination_qty"]
			else:
				destination = so.append("items", values)
		_persist(so)
		so.reload()
		new_rows = [row for row in so.items if row.name not in existing_names]
		expected_new = 1 if mode == "new" else 0
		if len(new_rows) != expected_new or len(so.items) != len(existing_names) + expected_new:
			frappe.throw(_("Unexpected schedule row changes; the rebalance was rolled back."))
		destination = new_rows[0] if expected_new else next(row for row in so.items if row.name == destination.name)
		_validate_result(before, so, source.name, destination, preview, financials)
		# Recheck fresh linked-document state before completing the transaction.
		_validate_dependencies(so, next(row for row in so.items if row.name == source.name))
		_validate_delivered_links(next(row for row in so.items if row.name == source.name))
		if mode == "merge":
			_validate_dependencies(so, destination)
			_validate_delivered_links(destination)
		comment = so.add_comment("Edit", _(
			"Schedule rebalance: {0}; source {1}: {8} to {2} on {3}; destination {4}: {5} on {6}; transferred {9}. Remarks: {7}"
		).format(*[frappe.utils.escape_html(str(value)) for value in (
			source.item_code, source.name, preview["retained_qty"], preview["old_date"],
			destination.name, preview["destination_qty"], preview["new_date"], reason.strip(), preview["original_qty"], preview["move_qty"],
		)]))
		# save() normally writes a Version; explicitly create one when tracking is off.
		if not so.meta.track_changes:
			version = frappe.new_doc("Version")
			if version.update_version_info(before, so):
				# Narrow audit-record bypass, after SO write/create authorization above.
				version.insert(ignore_permissions=True)
		return {"sales_order": so.name, "source": source.name, "destination": destination.name, "audit": comment.name}
	except Exception:
		frappe.db.rollback(save_point=savepoint)
		raise


def remove_empty_schedule(source_so_detail, reason):
	"""Remove an unreferenced zero-quantity submitted SO row through parent save."""
	if not isinstance(reason, str) or not reason.strip() or len(reason.strip()) > 1000:
		frappe.throw(_("Enter remarks of 1 to 1000 characters."))
	so, source = _load_source(source_so_detail, lock=True)
	if flt(source.qty) != 0:
		frappe.throw(_("Only a zero-quantity schedule can be removed."))
	_validate_dependencies(so, source)
	_validate_delivered_links(source)
	if not scheduling._can_remove_schedule_item(source):
		frappe.throw(_("This zero-quantity schedule has linked transactions or fulfillment history and must be retained."))
	_validate_original_stock_quantities(so)
	before = frappe.get_doc(deepcopy(so.as_dict()))
	financials = _financial_snapshot(so)
	sp = "remove_empty_schedule"
	frappe.db.savepoint(sp)
	try:
		so.remove(source)
		_persist(so)
		so.reload()
		if any(row.name == source.name for row in so.items):
			frappe.throw(_("The zero-quantity schedule was not removed."))
		changes = _financial_changes(financials, _financial_snapshot(so))
		if changes:
			frappe.throw(_("The schedule removal changed Sales Order commercial values and was rolled back."))
		comment = so.add_comment("Edit", _("Removed empty schedule {0} for {1}. Remarks: {2}").format(
			frappe.utils.escape_html(source.name), frappe.utils.escape_html(source.item_code),
			frappe.utils.escape_html(reason.strip())))
		if not so.meta.track_changes:
			version = frappe.new_doc("Version")
			if version.update_version_info(before, so):
				version.insert(ignore_permissions=True)
		from qcmc_logic.api.delivery_workbench_collaboration import notify_change
		notify_change(so)
		return {"sales_order": so.name, "removed_schedule": source.name, "audit": comment.name}
	except Exception:
		frappe.db.rollback(save_point=sp)
		raise


def _load_source(detail, lock=True):
	frappe.throw(_("Sales Order Item splitting is retired. Use SO Delivery Schedule records for delivery planning."))


def _prepare(so, source, quantity, delivery_date):
	validate_schedule_change(so, source)
	_validate_workflow(so)
	_validate_dependencies(so, source)
	_validate_original_stock_quantities(so)
	new_date = getdate(delivery_date) if delivery_date else None
	if not new_date or new_date < getdate(today()) or new_date < getdate(so.transaction_date):
		frappe.throw(_("Choose a delivery date on or after today and the order date."))
	if new_date == getdate(_schedule_date(source)):
		frappe.throw(_("Choose a different delivery date for the transferred quantity."))
	move_qty = _quantity(quantity, source, allow_negative=True)
	draft_qty = _draft_quantity(source.name)
	_validate_delivered_links(source)
	retained_qty = flt(flt(source.qty) - move_qty, source.precision("qty"))
	available = flt(source.qty) - flt(source.delivered_qty) - draft_qty
	if retained_qty < 0 or move_qty > available:
		frappe.throw(_("Move only the unallocated balance; delivered and active DR quantities must stay on the original schedule."))
	fields = _copy_fields(source)
	candidates = [row for row in so.items if row.name != source.name
		and _schedule_date(row) == str(new_date) and _same_context(source, row, fields)]
	target = candidates[0] if candidates else None
	mode = "move" if retained_qty == 0 else "merge" if target else "new"
	if move_qty < 0 and not target:
		frappe.throw(_("Increasing quantity requires a compatible existing schedule on the selected date."))
	if mode == "new":
		so.check_permission("create")  # Match ERPNext's permission when adding a row.
	destination_qty = flt(target.qty) + move_qty if mode == "merge" else move_qty
	if mode == "merge":
		validate_schedule_change(so, target)
		_validate_dependencies(so, target)
		_validate_delivered_links(target)
		target_floor = flt(target.delivered_qty) + _draft_quantity(target.name)
		if destination_qty <= 0 or destination_qty < target_floor:
			frappe.throw(_("The other schedule must retain its delivered and active DR quantities and a positive balance. To move it completely, rebalance that schedule to zero."))
	for value in (move_qty, retained_qty):
		for uom, qty in ((source.uom, value), (source.stock_uom, value * flt(source.conversion_factor))):
			if frappe.db.get_value("UOM", uom, "must_be_whole_number") and not float(qty).is_integer():
				frappe.throw(_("The split must respect whole-number quantities for UOM {0}.").format(uom))
	state = hashlib.sha256(frappe.as_json({
		"order": so.as_dict(), "active_dr_qty": draft_qty,
		"move_qty": move_qty, "new_date": str(new_date), "mode": mode, "target": target.name if mode == "merge" else None,
	}).encode()).hexdigest()
	return {"sales_order": so.name, "source": source.name, "original_qty": source.qty,
		"delivered_qty": source.delivered_qty, "active_dr_qty": draft_qty,
		"available_qty": available, "retained_qty": retained_qty, "move_qty": move_qty,
		"old_date": _schedule_date(source), "new_date": str(new_date), "state": state,
		"mode": mode, "target": target.name if mode == "merge" else None,
		"destination_qty": destination_qty, "existing_schedule": bool(target)}


def _schedule_date(row):
	return str(row.get("custom_next_scheduling_date") or row.delivery_date)


def _same_context(source, target, fields):
	for df in target.meta.fields:
		if df.get("is_custom_field") and df.fieldname not in set(fields) | {"custom_next_scheduling_date"}:
			if target.get(df.fieldname) not in (None, "", 0, False):
				return False
	return source.item_code == target.item_code and source.warehouse == target.warehouse and all(
		_field_equal(source, target, field) for field in fields if field != "delivery_date"
	)


def _field_equal(left, right, field):
	a, b = left.get(field), right.get(field)
	if a in (None, "") and b in (None, ""):
		return True
	if field in ("delivery_date", "transaction_date") and a and b:
		return getdate(a) == getdate(b)
	return a == b


def _resolve_quantity(source, quantity, retained_quantity):
	if retained_quantity is None:
		return quantity
	if quantity is not None:
		frappe.throw(_("Specify either the retained quantity or the quantity to move."))
	# Subtract on the server using decimals: a browser's 0.3 - 0.1 must not
	# become 0.19999999999999998 and fail the schedule precision check.
	_quantity(retained_quantity, source, allow_zero=True)
	difference = Decimal(str(source.qty)) - Decimal(str(retained_quantity))
	if difference == 0:
		frappe.throw(_("Enter a quantity different from the current schedule quantity."))
	return str(difference)


def _quantity(value, source, allow_zero=False, allow_negative=False):
	try:
		decimal = Decimal(str(value))
		precision = source.precision("qty")
		if (not decimal.is_finite() or (decimal == 0 and not allow_zero)
			or (decimal < 0 and not allow_negative) or decimal != decimal.quantize(Decimal(1).scaleb(-precision))):
			raise ValueError
	except (InvalidOperation, ValueError, TypeError):
		frappe.throw(_("Enter a valid, finite quantity within the schedule quantity precision."))
	if not math.isfinite(float(decimal)):
		frappe.throw(_("Invalid split quantity."))
	if flt(source.conversion_factor) <= 0:
		frappe.throw(_("The schedule has an invalid UOM conversion factor."))
	return float(decimal)


def validate_schedule_change(so, source):
	"""Compatibility validation for the retired Sales Order Item split API."""
	so.check_permission("write")
	from qcmc_logic.api.sales_order_delivery_eligibility import is_open_sales_order_for_delivery
	if (not is_open_sales_order_for_delivery(so)
		or so.custom_so_type not in ("FOB", "FOB-DIRECT", "REGULAR")
		or so.get("is_subcontracted") or source.get("delivered_by_supplier")):
		frappe.throw(_("This Sales Order is not eligible for delivery schedule changes."))
	if not source.warehouse or frappe.db.get_value("Warehouse", source.warehouse, "custom_is_province"):
		frappe.throw(_("Schedule changes require a non-provincial warehouse."))
	scheduling._validate_sales_coordinator_access(so, source, require_transact=True)


def _validate_workflow(so):
	# A same-state save alone does not check workflow state editability.
	workflow_name = so.meta.get_workflow()
	if workflow_name:
		workflow = frappe.get_cached_doc("Workflow", workflow_name)
		state = so.get(workflow.workflow_state_field)
		allowed = {row.allow_edit for row in workflow.states if row.state == state}
		if frappe.session.user != "Administrator" and not allowed.intersection(frappe.get_roles()):
			frappe.throw(_("Your role cannot edit the Sales Order in its current workflow state."), frappe.PermissionError)


def _validate_dependencies(so, source):
	for field in COUNTERS:
		if flt(source.get(field)):
			frappe.throw(_("Schedule {0} has {1}; resolve its commitments before splitting.").format(source.name, field))
	if any(source.get(field) for field in ("prevdoc_docname", "quotation_item", "blanket_order", "material_request_item", "purchase_order_item", "purchase_order", "material_request", "fg_item", "target_warehouse", "supplier", "ensure_delivery_based_on_produced_serial_no")):
		frappe.throw(_("Referenced quotation, blanket-order or purchasing schedules cannot be split yet."))
	if so.get("packed_items") or frappe.db.exists("Product Bundle", source.item_code):
		frappe.throw(_("Product bundle schedules cannot be split yet."))
	indirect_invoice = frappe.db.sql("""
		SELECT sii.name FROM `tabSales Invoice Item` sii
		JOIN `tabSales Invoice` si ON si.name = sii.parent
		JOIN `tabDelivery Note Item` dni ON dni.name = sii.dn_detail OR dni.parent = sii.delivery_note
		WHERE dni.against_sales_order = %s AND si.docstatus < 2
		LIMIT 1 FOR UPDATE
	""", so.name)
	if indirect_invoice:
		frappe.throw(_("This order has an invoice linked through a Delivery Note; splitting is blocked."))
	# The standard updater recreates order-wide reservations. Block them at order
	# scope rather than risking changes to reservations on unrelated item rows.
	for doctype, filters in (
		("Stock Reservation Entry", {"voucher_type": "Sales Order", "voucher_no": so.name}),
		("Sales Invoice Item", {"sales_order": so.name}),
		("Pick List Item", {"sales_order": so.name}),
		("Work Order", {"sales_order": so.name}),
		("Purchase Order Item", {"sales_order": so.name}),
		("Material Request Item", {"sales_order": so.name}),
		("Production Plan Sales Order", {"sales_order": so.name}),
		("Production Plan Item", {"sales_order": so.name}),
		("Delivery Schedule Item", {"sales_order": so.name}),
	):
		if frappe.db.get_value(doctype, dict(filters, docstatus=["<", 2]), "name", for_update=True):
			frappe.throw(_("Sales Order {0} has an active {1}; splitting is blocked.").format(so.name, doctype))
	# Runtime metadata includes custom Link fields (including the EPS secondary WO
	# table). Unknown live links fail closed instead of being silently copied.
	for field in frappe.get_all("DocField", filters={"fieldtype": "Link", "options": "Sales Order Item"}, fields=["parent", "fieldname"]):
		_validate_inbound_link(field.parent, field.fieldname, source.name)
	for field in frappe.get_all("Custom Field", filters={"fieldtype": "Link", "options": "Sales Order Item"}, fields=["dt", "fieldname"]):
		_validate_inbound_link(field.dt, field.fieldname, source.name)
	_copy_fields(source)  # Fail before writes for unreviewed custom business values.


def _validate_inbound_link(doctype, fieldname, source):
	meta = frappe.get_meta(doctype)
	if meta.is_virtual or meta.issingle:
		frappe.throw(_("Unsupported SO item reference in {0}; split requires review.").format(doctype))
	if frappe.db.get_value(doctype, {fieldname: source, "docstatus": ["<", 2]}, "name", for_update=True):
		frappe.throw(_("Schedule has an active {0} reference; splitting is blocked.").format(doctype))


def _copy_fields(source):
	fields = set(COPY_FIELDS)
	# Accounting dimensions are site-specific; retain their exact row values.
	from erpnext.accounts.doctype.accounting_dimension.accounting_dimension import get_accounting_dimensions
	fields.update(get_accounting_dimensions())
	for df in source.meta.fields:
		if df.get("is_custom_field") and df.fieldname not in fields | {"custom_next_scheduling_date"}:
			if source.get(df.fieldname) not in (None, "", 0, False):
				frappe.throw(_("Custom schedule field {0} needs split handling before this row can be split.").format(df.label))
	return [field for field in fields if source.meta.has_field(field)]


def validate_compatible_schedules(source, target):
	fields = set(_copy_fields(source)) | set(_copy_fields(target))
	if any(not _field_equal(source, target, field) for field in fields if field != "delivery_date"):
		frappe.throw(_("Schedules have different pricing, UOM or business details. Use Split Schedule to create a separate row."))


def _validate_delivered_links(source):
	rows = frappe.db.sql("""
		SELECT dni.qty, dn.is_return FROM `tabDelivery Note Item` dni
		JOIN `tabDelivery Note` dn ON dn.name = dni.parent
		WHERE dni.so_detail = %s AND dn.docstatus = 1 FOR UPDATE
	""", source.name, as_dict=True)
	if any(row.is_return or flt(row.qty) < 0 for row in rows):
		frappe.throw(_("Returned schedules need reconciliation before splitting."))
	if flt(sum(flt(row.qty) for row in rows), source.precision("qty")) != flt(source.delivered_qty, source.precision("qty")):
		frappe.throw(_("Delivered quantity does not reconcile with submitted Delivery Notes."))


def _persist(so):
	"""Run the supported submitted-order lifecycle, preserving copied row context.

	ERPNext update_child_qty_rate cannot be used as-is: set_order_defaults resets
	warehouse/taxes and omits custom context. Keep its validation/refresh sequence
	but save the complete parent, without direct child inserts or db.set_value.
	"""
	from erpnext.stock.doctype.packed_item.packed_item import make_packing_list
	# Database-loaded Date fields are date objects, while dialog/new-row dates
	# may be strings. ERPNext validate_delivery_date() calls max() on the item
	# dates before coercing them; normalize the complete document first.
	if so.get("delivery_date"):
		so.delivery_date = getdate(so.delivery_date)
	for row in so.items:
		if row.delivery_date:
			row.delivery_date = getdate(row.delivery_date)
	so.set_qty_as_per_stock_uom()
	for row in so.items:
		if row.meta.has_field("total_weight"):
			row.total_weight = flt(flt(row.weight_per_unit) * flt(row.stock_qty), row.precision("total_weight"))
	so.calculate_taxes_and_totals()
	so.set_total_in_words()
	make_packing_list(so)
	so.set_gross_profit()
	frappe.get_cached_doc("Authorization Control").validate_approving_authority(
		so.doctype, so.company, so.base_grand_total,
	)
	so.set_payment_schedule()
	so.validate_selling_price()
	so.validate_for_duplicate_items()
	so.validate_warehouse()
	so.validate_uom_is_integer("uom", "qty")
	so.validate_uom_is_integer("stock_uom", "stock_qty")
	# Submitted saves omit validate() in Frappe; explicitly retain controller and
	# custom permission/business validators before using the scoped field bypass.
	so.run_method("validate")
	so.flags.ignore_validate_update_after_submit = True
	try:
		so.save(ignore_version=False)
	finally:
		so.flags.ignore_validate_update_after_submit = False
	so.update_reserved_qty()
	so.update_project()
	so.update_prevdoc_status("submit")
	so.update_delivery_status()
	so.update_blanket_order()
	so.update_billing_percentage()
	so.set_status()


def _validate_original_stock_quantities(so):
	# Recalculating the complete submitted order must not silently repair stale
	# stock quantities on this or an unrelated row during a scheduling operation.
	for row in so.items:
		precision = row.precision("stock_qty")
		expected = flt(flt(row.qty) * flt(row.conversion_factor), precision)
		actual = flt(row.stock_qty, precision)
		if actual != expected:
			frappe.throw(_(
				"Sales Order {0}, item {1}, has inconsistent stock quantity: {2}; expected {3} from quantity × conversion factor. Correct the existing order data before rebalancing."
			).format(*[frappe.utils.escape_html(str(value)) for value in (so.name, row.item_code, actual, expected)]))


def _financial_snapshot(so):
	commercial_keys = (
		"item_code", "warehouse", "uom", "stock_uom", "conversion_factor", "rate", "base_rate",
		"discount_amount", "base_discount_amount",
		# ERPNext derives net_rate after discounts and inclusive taxes. Its per-row
		# rounding can differ by a currency precision when one SO row is split;
		# aggregate persisted item amounts below instead of treating that derived
		# rate as a separate commercial term.
		"discount_percentage", "item_tax_template", "item_tax_rate",
		"income_account", "cost_center", "project",
	)
	commercial_amounts = (
		"qty", "stock_qty", "amount", "base_amount", "net_amount", "base_net_amount",
		"distributed_discount_amount",
	)
	item_totals = {}
	for row in so.items:
		key = tuple(str(row.get(field) or "") for field in commercial_keys)
		totals = item_totals.setdefault(key, {field: Decimal("0") for field in commercial_amounts})
		for field in commercial_amounts:
			if row.meta.has_field(field):
				totals[field] += Decimal(str(flt(row.get(field), row.precision(field))))
	taxes = []
	for row in so.get("taxes", []):
		values = {field: row.get(field) or "" for field in ("account_head", "charge_type")}
		values.update({field: flt(row.get(field), row.precision(field))
			for field in ("rate", "tax_amount", "base_tax_amount", "total", "base_total")})
		taxes.append(values)
	payments = []
	for row in so.get("payment_schedule", []):
		values = {"payment_term": row.get("payment_term") or "",
			"due_date": str(getdate(row.due_date)) if row.get("due_date") else None}
		values.update({field: flt(row.get(field), row.precision(field))
			for field in ("invoice_portion", "payment_amount", "base_payment_amount")})
		payments.append(values)
	# Payment obligations do not change when identical terms are merely reordered.
	payments.sort(key=lambda values: frappe.as_json(values))
	return {
		"parent": {field: flt(so.get(field), so.precision(field)) for field in FINANCIAL_FIELDS if so.meta.has_field(field)},
		"items": [{"commercial_terms": key, "totals": totals} for key, totals in sorted(item_totals.items())],
		"stock_qty": sum(Decimal(str(row.stock_qty)) for row in so.items),
		"taxes": taxes,
		"payments": payments,
	}


def _financial_changes(before, after, path=""):
	"""Explain a real invariant failure without losing the transaction rollback."""
	labels = {"parent": "Order", "stock_qty": "Stock quantity", "payments": "Payment schedule", "taxes": "Taxes"}
	if isinstance(before, dict) and isinstance(after, dict):
		changes = []
		for key in sorted(before.keys() | after.keys()):
			label = labels.get(key, key.replace("_", " ").capitalize())
			changes.extend(_financial_changes(before.get(key), after.get(key), f"{path} / {label}" if path else label))
		return changes
	if isinstance(before, list) and isinstance(after, list):
		changes = []
		if len(before) != len(after):
			changes.append(f"{path} / Number of rows: {len(before)} → {len(after)}")
		for index, (old, new) in enumerate(zip(before, after), 1):
			changes.extend(_financial_changes(old, new, f"{path} / Row {index}"))
		return changes
	return [f"{path}: {before} → {after}"] if before != after else []


def _validate_result(before, after, source_name, new_row, preview, financials):
	changes = _financial_changes(financials, _financial_snapshot(after))
	if changes:
		details = "<br>".join(frappe.utils.escape_html(change) for change in changes[:8])
		frappe.throw(_("The rebalance was rolled back because these values changed:") + "<br>" + details)
	old_rows = {row.name: row for row in before.items}
	mode = preview.get("mode", "new")
	expected_names = set(old_rows) | ({new_row.name} if mode == "new" else set())
	if {row.name for row in after.items} != expected_names:
		frappe.throw(_("An existing schedule was removed or replaced unexpectedly."))
	for row in after.items:
		if mode == "new" and row.name == new_row.name:
			if row.docstatus != 1 or flt(row.qty) != preview["move_qty"]:
				frappe.throw(_("The new schedule did not retain its submitted quantity."))
			for field in ("delivered_qty", "billed_amt", "produced_qty", "picked_qty", "ordered_qty", "stock_reserved_qty"):
				if flt(row.get(field)):
					frappe.throw(_("New schedules cannot inherit fulfillment values."))
			if row.get("custom_next_scheduling_date"):
				frappe.throw(_("New schedules cannot inherit a scheduling-date override."))
			continue
		old = old_rows[row.name]
		if row.name == source_name:
			expected_qty = old.qty if mode == "move" else preview["retained_qty"]
			if flt(row.qty) != expected_qty:
				frappe.throw(_("The original schedule quantity changed unexpectedly."))
		elif mode == "merge" and row.name == preview["target"]:
			if flt(row.qty) != preview["destination_qty"]:
				frappe.throw(_("The destination schedule quantity changed unexpectedly."))
		elif row.qty != old.qty:
			frappe.throw(_("An unrelated schedule quantity changed."))
		for field in _copy_fields(old) + ["delivered_qty", *COUNTERS]:
			if mode == "move" and row.name == source_name and field == "delivery_date":
				continue
			if not _field_equal(row, old, field):
				frappe.throw(_("The split unexpectedly changed schedule field {0}.").format(field))
	if mode == "new":
		original = old_rows[source_name]
		for field in _copy_fields(original):
			if field != "delivery_date" and not _field_equal(new_row, original, field):
				frappe.throw(_("The new schedule did not preserve {0}.").format(field))
	if _schedule_date(new_row) != preview["new_date"]:
		frappe.throw(_("The new schedule date changed unexpectedly."))


def lock_orders(names):
	"""Common parent-first mutex for scheduling and document allocation writers."""
	for name in sorted(set(names)):
		frappe.db.sql("SELECT name FROM `tabSales Order` WHERE name = %s FOR UPDATE", name)


def _draft_quantity(detail, exclude=""):
	rows = frappe.db.sql("""
		SELECT dni.qty FROM `tabDelivery Note Item` dni
		JOIN `tabDelivery Note` dn ON dn.name = dni.parent
		WHERE dni.so_detail = %s AND dn.docstatus = 0 AND dn.name != %s
		FOR UPDATE
	""", (detail, exclude), as_dict=True)
	if any(flt(row.qty) < 0 for row in rows):
		frappe.throw(_("Negative draft allocations need reconciliation before scheduling."))
	return sum(flt(row.qty) for row in rows)


def lock_order_references(doc, method=None):
	"""Serialize normal ORM allocation writes with splitting; no external writes.

	Called before validation and submitted updates/cancellation for known allocation
	documents. Revalidates DN allocations after acquiring the SO mutex.
	"""
	names = set()
	for row in [doc, *doc.get_all_children()]:
		for field in ("sales_order", "against_sales_order"):
			if row.get(field):
				names.add(row.get(field))
		if row.get("voucher_type") == "Sales Order" and row.get("voucher_no"):
			names.add(row.voucher_no)
		for field in ("sales_order_item", "so_detail"):
			if row.get(field):
				parent = frappe.db.get_value("Sales Order Item", row.get(field), "parent")
				if parent:
					names.add(parent)
	if doc.doctype == "Sales Order":
		if not doc.is_new():
			names.add(doc.name)
	if doc.doctype == "Sales Order Item" and doc.get("parenttype") == "Sales Order" and doc.get("parent"):
		names.add(doc.parent)
	lock_orders(names)
	if doc.doctype in ("Sales Order", "Sales Order Item") and not doc.is_new():
		# check_if_latest runs before lifecycle hooks. Recheck after acquiring the
		# mutex so a save waiting behind a split cannot overwrite its new rows.
		modified = frappe.db.get_value(doc.doctype, doc.name, "modified", for_update=True)
		if str(modified) != str(doc._original_modified):
			frappe.throw(_("The Sales Order changed. Reload it before saving."), frappe.TimestampMismatchError)
	if doc.doctype == "Delivery Note" and method != "before_cancel" and not doc.get("is_return"):
		_validate_dn_allocation(doc)


def _validate_dn_allocation(doc):
	quantities = {}
	for row in doc.items:
		if row.so_detail:
			quantities[row.so_detail] = quantities.get(row.so_detail, 0) + flt(row.qty)
	for detail, qty in quantities.items():
		source = frappe.db.get_value("Sales Order Item", detail, ["qty", "delivered_qty"], as_dict=True, for_update=True)
		if not source:
			frappe.throw(_("The Sales Order schedule no longer exists."))
		other = _draft_quantity(detail, doc.name or "")
		# An already submitted DN is included in delivered_qty; do not count twice.
		old_qty = 0
		if not doc.is_new() and frappe.db.get_value("Delivery Note", doc.name, "docstatus", for_update=True) == 1:
			old_qty = sum(flt(row.qty) for row in frappe.get_doc("Delivery Note", doc.name, for_update=True).items if row.so_detail == detail)
		if qty + flt(other) + flt(source.delivered_qty) - old_qty > flt(source.qty) + 1e-9:
			frappe.throw(_("Delivery Note exceeds the unallocated Sales Order schedule quantity. Refresh the schedule."))
