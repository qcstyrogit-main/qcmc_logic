import frappe
from frappe import _

from qcmc_logic.customs.territory_access_permissions import (
	get_user_allowed_territories,
	has_territory_access,
)
from qcmc_logic.utils import (
	_get_effective_warehouse_access_names,
	get_user_allowed_warehouses,
)


SCHEDULING_ROLES = {"Sales Coordinator"}


def execute(filters=None):
	filters = frappe._dict(filters or {})
	columns = [
		{"label": _("Sales Order"), "fieldname": "sales_order", "fieldtype": "Link", "options": "Sales Order", "width": 150},
		{"label": _("Customer"), "fieldname": "customer_name", "fieldtype": "Data", "width": 220},
		{"label": _("SO Type"), "fieldname": "so_type", "fieldtype": "Data", "width": 110},
		{"label": _("Item Code"), "fieldname": "item_code", "fieldtype": "Link", "options": "Item", "width": 150},
		{"label": _("Item Name"), "fieldname": "item_name", "fieldtype": "Data", "width": 220},
		{"label": _("Warehouse"), "fieldname": "warehouse", "fieldtype": "Link", "options": "Warehouse", "width": 180},
		{"label": _("Ordered Qty"), "fieldname": "qty", "fieldtype": "Float", "width": 110},
		{"label": _("Delivered Qty"), "fieldname": "delivered_qty", "fieldtype": "Float", "width": 110},
		{"label": _("Balance Qty"), "fieldname": "balance_qty", "fieldtype": "Float", "width": 110},
		{"label": _("Active DR Qty"), "fieldname": "draft_dr_qty", "fieldtype": "Float", "width": 110},
		{"label": _("Available Qty"), "fieldname": "available_qty", "fieldtype": "Float", "width": 110},
		{"label": _("Warehouse Stock"), "fieldname": "actual_qty", "fieldtype": "Float", "width": 120},
		{"label": _("Original Delivery Date(s)"), "fieldname": "delivery_dates", "fieldtype": "Data", "width": 170},
		{"label": _("Available From"), "fieldname": "available_from", "fieldtype": "Date", "width": 120},
	]
	if not filters.get("delivery_date") or not filters.get("company"):
		return columns, [], _("Select a company and delivery date to view eligible Sales Orders."), None, []
	conditions = ["so.company = %(company)s"]
	values = {"delivery_date": filters.delivery_date, "company": filters.company}
	if filters.get("warehouse"):
		conditions.append("soi.warehouse = %(warehouse)s")
		values["warehouse"] = filters.warehouse
	_apply_sales_coordinator_scope(conditions, values)
	rows = frappe.db.sql("""
		SELECT soi.name AS so_detail, so.name AS sales_order, so.customer_name,
			so.custom_so_type AS so_type, soi.item_code, soi.item_name, soi.warehouse,
			soi.qty, soi.delivered_qty, (soi.qty - soi.delivered_qty) AS balance_qty,
			IFNULL(draft_dr.qty, 0) AS draft_dr_qty,
			(soi.qty - soi.delivered_qty - IFNULL(draft_dr.qty, 0)) AS available_qty,
			IFNULL(bin.actual_qty, 0) AS actual_qty,
			soi.delivery_date,
			COALESCE(soi.custom_next_scheduling_date, soi.delivery_date) AS available_from
		FROM `tabSales Order` so
		JOIN `tabSales Order Item` soi ON soi.parent = so.name
		JOIN `tabWarehouse` wh ON wh.name = soi.warehouse
		LEFT JOIN `tabBin` bin ON bin.item_code = soi.item_code AND bin.warehouse = soi.warehouse
		LEFT JOIN (
			SELECT dni.so_detail, SUM(dni.qty) AS qty
			FROM `tabDelivery Note Item` dni
			JOIN `tabDelivery Note` dn ON dn.name = dni.parent
			WHERE dn.docstatus = 0
			GROUP BY dni.so_detail
		) draft_dr ON draft_dr.so_detail = soi.name
		WHERE so.docstatus = 1 AND so.status = 'To Deliver and Bill'
			AND so.custom_so_type IN ('FOB', 'FOB-DIRECT', 'REGULAR')
			AND IFNULL(wh.custom_is_province, 0) = 0
			AND (soi.qty - soi.delivered_qty - IFNULL(draft_dr.qty, 0)) > 0
			AND COALESCE(soi.custom_next_scheduling_date, soi.delivery_date) <= %(delivery_date)s
			AND {conditions}
		ORDER BY available_from, so.name, soi.idx
	""".format(conditions=" AND ".join(conditions)), values, as_dict=True)
	return columns, rows, _("{0} eligible item(s) found.").format(len(rows)), None, [
		{"value": len({row.sales_order for row in rows}), "indicator": "Blue", "label": _("Sales Orders"), "datatype": "Int"},
		{"value": len(rows), "indicator": "Green", "label": _("Schedules"), "datatype": "Int"},
	]


def _consolidate_rows(rows):
	consolidated = {}
	for row in rows:
		key = (row.sales_order, row.item_code, row.warehouse)
		if key not in consolidated:
			consolidated[key] = frappe._dict(row)
			consolidated[key].so_details = [row.so_detail]
			consolidated[key].delivery_dates = {str(row.delivery_date)}
			continue
		target = consolidated[key]
		target.so_details.append(row.so_detail)
		target.delivery_dates.add(str(row.delivery_date))
		for fieldname in ("qty", "delivered_qty", "balance_qty", "draft_dr_qty", "available_qty"):
			target[fieldname] = frappe.utils.flt(target[fieldname]) + frappe.utils.flt(row[fieldname])
		target.available_from = max(target.available_from, row.available_from)

	for row in consolidated.values():
		row.delivery_dates = ", ".join(sorted(row.delivery_dates))
	return list(consolidated.values())


@frappe.whitelist()
def get_related_schedules(source_so_detail):
	_validate_scheduling_role()
	source_link = frappe.db.get_value("Sales Order Item", source_so_detail, ["parent", "item_code", "warehouse"], as_dict=True)
	if not source_link:
		frappe.throw(_("Sales Order Item {0} was not found.").format(source_so_detail))
	so = frappe.get_doc("Sales Order", source_link.parent)
	source = next((item for item in so.items if item.name == source_so_detail), None)
	if not source:
		frappe.throw(_("Selected schedule does not belong to the Sales Order."))
	_validate_sales_coordinator_access(so, source, require_transact=True)

	rows = frappe.db.sql(
		"""
		SELECT soi.name, soi.delivery_date, soi.qty, soi.delivered_qty, IFNULL(draft_dr.qty, 0) AS draft_dr_qty,
			(soi.qty - soi.delivered_qty - IFNULL(draft_dr.qty, 0)) AS available_qty
		FROM `tabSales Order Item` soi
		LEFT JOIN (
			SELECT dni.so_detail, SUM(dni.qty) AS qty
			FROM `tabDelivery Note Item` dni
			JOIN `tabDelivery Note` dn ON dn.name = dni.parent
			WHERE dn.docstatus = 0
			GROUP BY dni.so_detail
		) draft_dr ON draft_dr.so_detail = soi.name
		WHERE soi.parent = %s AND soi.item_code = %s AND soi.warehouse = %s AND soi.name != %s
		ORDER BY soi.delivery_date, soi.idx, soi.name
		""",
		(source_link.parent, source_link.item_code, source_link.warehouse, source_so_detail),
		as_dict=True,
	)
	return rows


@frappe.whitelist()
def adjust_scheduled_quantity(source_so_detail, target_so_detail, new_qty, remarks=None):
	_validate_scheduling_role()
	if not target_so_detail:
		frappe.throw(_("Select a schedule for the quantity difference."))
	if source_so_detail == target_so_detail:
		frappe.throw(_("Select a different schedule for the quantity difference."))
	if not remarks or not str(remarks).strip():
		frappe.throw(_("Remarks are required for a quantity adjustment."))

	source_link = frappe.db.get_value("Sales Order Item", source_so_detail, ["parent", "item_code", "warehouse"], as_dict=True)
	if not source_link:
		frappe.throw(_("Sales Order Item {0} was not found.").format(source_so_detail))
	so_item_rows = frappe.db.sql(
		"""
		SELECT name, parent, item_code, warehouse, qty, delivered_qty, delivery_date
		FROM `tabSales Order Item`
		WHERE parent = %s AND item_code = %s AND warehouse = %s
		ORDER BY delivery_date, idx, name
		FOR UPDATE
		""",
		(source_link.parent, source_link.item_code, source_link.warehouse),
		as_dict=True,
	)
	details = _lock_sales_order_items([row.name for row in so_item_rows])
	if target_so_detail not in {row.name for row in details}:
		frappe.throw(_("The selected transfer schedule must be for the same Sales Order item and warehouse."))

	so = frappe.get_doc("Sales Order", details[0].parent)
	if so.docstatus != 1 or so.status != "To Deliver and Bill":
		frappe.throw(_("Sales Order {0} is not eligible for scheduling.").format(so.name))
	items = {item.name: item for item in so.items}
	source = items.get(source_so_detail)
	target = items.get(target_so_detail)
	if not source or not target:
		frappe.throw(_("Selected schedules do not belong to the Sales Order."))
	if (source.item_code, source.warehouse) != (target.item_code, target.warehouse):
		frappe.throw(_("Quantity can only be moved between schedules for the same item and warehouse."))
	_validate_sales_coordinator_access(so, source, require_transact=True)
	_validate_sales_coordinator_access(so, target, require_transact=True)

	new_qty = frappe.utils.flt(new_qty)
	old_qty = frappe.utils.flt(source.qty)
	delta = new_qty - old_qty
	if new_qty <= 0:
		frappe.throw(_("The adjusted quantity must be greater than zero."))
	if not delta:
		frappe.throw(_("The adjusted quantity must be different from the current quantity."))
	if delta < 0 and frappe.utils.flt(source.delivered_qty) > new_qty:
		frappe.throw(_("The adjusted quantity cannot be less than the delivered quantity."))
	source_draft_qty = _get_draft_delivery_note_qty(source.name)
	if delta < 0 and (frappe.utils.flt(source.delivered_qty) + source_draft_qty) > new_qty:
		frappe.throw(_("The adjusted quantity cannot be less than the delivered quantity plus active DR quantity."))

	before_doc = frappe.get_doc("Sales Order", so.name)
	if delta > 0:
		target_available_qty = frappe.utils.flt(target.qty) - frappe.utils.flt(target.delivered_qty) - _get_draft_delivery_note_qty(target.name)
		if target_available_qty < delta:
			frappe.throw(_("The selected schedule has only {0} available to deduct.").format(target_available_qty))
		new_target_qty = frappe.utils.flt(target.qty) - delta
	else:
		new_target_qty = frappe.utils.flt(target.qty) - delta
	_update_sales_order_schedule_quantities(so, {source.name: new_qty, target.name: new_target_qty})
	after_doc = frappe.get_doc("Sales Order", so.name)
	source = next((item for item in after_doc.items if item.name == source_so_detail), source)
	target = next((item for item in after_doc.items if item.name == target_so_detail), target)
	_record_quantity_adjustment_history(before_doc, after_doc, source, target, old_qty, delta, remarks)
	return _("Schedule quantity updated and recorded in Sales Order history.")


def _update_sales_order_schedule_quantities(so, qty_by_detail):
	removed_details = []
	for item in list(so.items):
		if item.name in qty_by_detail:
			item.qty = frappe.utils.flt(qty_by_detail[item.name])
			if item.qty <= 0 and _can_remove_schedule_item(item):
				removed_details.append(item.name)
				so.remove(item)
				continue
			item.stock_qty = item.qty * frappe.utils.flt(item.conversion_factor or 1)
			_set_sales_order_item_amounts(item)
	for idx, item in enumerate(so.items, start=1):
		item.idx = idx

	so.run_method("calculate_taxes_and_totals")

	parent_fields = [
		"total_qty", "total", "net_total", "base_total", "base_net_total",
		"grand_total", "base_grand_total", "rounded_total", "base_rounded_total",
		"total_taxes_and_charges", "base_total_taxes_and_charges",
		"discount_amount", "base_discount_amount", "in_words", "base_in_words",
	]
	parent_values = {field: so.get(field) for field in parent_fields if so.meta.has_field(field)}
	parent_values["modified"] = frappe.utils.now()
	parent_values["modified_by"] = frappe.session.user
	frappe.db.set_value("Sales Order", so.name, parent_values, update_modified=False)

	item_fields = [
		"idx", "qty", "stock_qty", "amount", "base_amount", "net_amount", "base_net_amount",
		"rate", "base_rate", "net_rate", "base_net_rate",
	]
	for item in so.items:
		if item.name in qty_by_detail or removed_details:
			frappe.db.set_value(
				"Sales Order Item",
				item.name,
				{field: item.get(field) for field in item_fields if item.meta.has_field(field)},
				update_modified=False,
			)

	for tax in so.get("taxes", []):
		tax.db_update()

	for detail in removed_details:
		frappe.delete_doc("Sales Order Item", detail, force=True, ignore_permissions=True)


@frappe.whitelist()
def cleanup_zero_schedules(sales_order):
	_validate_scheduling_role()
	so = frappe.get_doc("Sales Order", sales_order)
	if so.docstatus != 1:
		frappe.throw(_("Sales Order {0} must be submitted.").format(sales_order))
	before_doc = frappe.get_doc("Sales Order", sales_order)
	removed = []
	for item in list(so.items):
		if frappe.utils.flt(item.qty) == 0 and _can_remove_schedule_item(item):
			removed.append({"name": item.name, "item_code": item.item_code, "delivery_date": item.delivery_date})
			so.remove(item)
	for idx, item in enumerate(so.items, start=1):
		item.idx = idx
		frappe.db.set_value("Sales Order Item", item.name, "idx", idx, update_modified=False)
	for row in removed:
		frappe.delete_doc("Sales Order Item", row["name"], force=True, ignore_permissions=True)
	if removed:
		after_doc = frappe.get_doc("Sales Order", sales_order)
		_record_zero_schedule_cleanup_history(before_doc, after_doc, removed)
	return _("Removed zero schedule row(s): {0}").format(len(removed))


def _set_sales_order_item_amounts(item):
	item.amount = frappe.utils.flt(item.qty) * frappe.utils.flt(item.rate)
	item.base_amount = frappe.utils.flt(item.qty) * frappe.utils.flt(item.base_rate)
	item.net_amount = frappe.utils.flt(item.qty) * frappe.utils.flt(item.net_rate or item.rate)
	item.base_net_amount = frappe.utils.flt(item.qty) * frappe.utils.flt(item.base_net_rate or item.base_rate)


def _can_remove_schedule_item(item):
	linked_delivery_note_qty = frappe.db.sql(
		"""
		SELECT IFNULL(SUM(dni.qty), 0)
		FROM `tabDelivery Note Item` dni
		JOIN `tabDelivery Note` dn ON dn.name = dni.parent
		WHERE dni.so_detail = %s AND dn.docstatus < 2
		""",
		item.name,
	)[0][0]
	return not any(
		frappe.utils.flt(value)
		for value in (
			item.delivered_qty,
			item.billed_amt,
			item.produced_qty,
			item.picked_qty,
			linked_delivery_note_qty,
		)
	)


def _record_zero_schedule_cleanup_history(before_doc, after_doc, removed):
	version = frappe.new_doc("Version")
	if version.update_version_info(before_doc, after_doc):
		version.insert(ignore_permissions=True)
	lines = [_("Zero delivery schedule rows removed from Sales Order Delivery Scheduling:")]
	for row in removed:
		lines.append(
			_("{0}: {1}").format(
				frappe.bold(row["item_code"]),
				frappe.utils.formatdate(row["delivery_date"]),
			)
		)
	after_doc.add_comment("Edit", "<br>".join(lines))


def _record_quantity_adjustment_history(before_doc, after_doc, source, target, old_qty, delta, remarks):
	version = frappe.new_doc("Version")
	if version.update_version_info(before_doc, after_doc):
		version.insert(ignore_permissions=True)
	direction = _("increased") if delta > 0 else _("decreased")
	transfer_action = _("deducted from") if delta > 0 else _("moved to")
	message = _(
		"Delivery schedule quantity {0}: {1} from {2} to {3}; {4} {5} schedule {6}. Remarks: {7}"
	).format(direction, frappe.bold(source.item_code), old_qty, source.qty, abs(delta), transfer_action, target.delivery_date, frappe.utils.escape_html(remarks))
	after_doc.add_comment("Edit", message)


@frappe.whitelist()
def update_delivery_dates(so_details, delivery_date):
	_validate_scheduling_role()
	so_details = frappe.parse_json(so_details)
	if not so_details or not delivery_date:
		frappe.throw(_("Items and a new delivery date are required."))
	_lock_sales_order_items(so_details)
	before_docs = {}
	changes = {}
	for detail in so_details:
		row = frappe.db.get_value("Sales Order Item", detail, ["parent", "delivery_date"], as_dict=True)
		if not row:
			frappe.throw(_("Sales Order Item {0} was not found.").format(detail))
		so = frappe.get_doc("Sales Order", row.parent)
		if so.docstatus != 1 or so.status != "To Deliver and Bill" or so.custom_so_type not in ("FOB", "FOB-DIRECT", "REGULAR"):
			frappe.throw(_("Sales Order {0} is not eligible for scheduling.").format(row.parent))
		item = next((item for item in so.items if item.name == detail), None)
		if not item or item.qty <= item.delivered_qty:
			frappe.throw(_("Sales Order Item {0} has no undelivered quantity.").format(detail))
		if frappe.utils.flt(item.delivered_qty) > 0 or _get_draft_delivery_note_qty(detail) > 0:
			frappe.throw(_("Sales Order Item {0} already has delivered quantity or an active DR and cannot be moved to another date.").format(detail))
		if item.warehouse and frappe.db.get_value("Warehouse", item.warehouse, "custom_is_province"):
			frappe.throw(_("Sales Order Item {0} belongs to a provincial warehouse.").format(detail))
		_validate_sales_coordinator_access(so, item, require_transact=True)
		target = _find_existing_schedule_for_date(so, item, detail, delivery_date)
		if str(row.delivery_date or "") == str(delivery_date) and not target:
			continue
		before_docs.setdefault(row.parent, frappe.get_doc("Sales Order", row.parent))
		if target:
			_validate_sales_coordinator_access(so, target, require_transact=True)
			moved_qty = frappe.utils.flt(item.qty)
			_update_sales_order_schedule_quantities(
				so,
				{
					item.name: 0,
					target.name: frappe.utils.flt(target.qty) + moved_qty,
				},
			)
			frappe.db.set_value("Sales Order Item", item.name, "custom_next_scheduling_date", None)
			changes.setdefault(row.parent, []).append(
				{
					"item_code": item.item_code,
					"old_date": row.delivery_date,
					"new_date": delivery_date,
					"merged_to": target.delivery_date,
					"qty": moved_qty,
				}
			)
		else:
			changes.setdefault(row.parent, []).append(
				{"item_code": item.item_code, "old_date": row.delivery_date, "new_date": delivery_date}
			)
			frappe.db.set_value("Sales Order Item", detail, "delivery_date", delivery_date)
			frappe.db.set_value("Sales Order Item", detail, "custom_next_scheduling_date", None)
	for sales_order, sales_order_changes in changes.items():
		_record_delivery_date_history(
			before_docs[sales_order],
			frappe.get_doc("Sales Order", sales_order),
			sales_order_changes,
		)
	return _("Delivery dates updated and recorded in Sales Order history. The report has been refreshed.")


def _find_existing_schedule_for_date(so, source_item, source_detail, delivery_date):
	delivery_date = frappe.utils.getdate(delivery_date)
	for item in so.items:
		if item.name == source_detail:
			continue
		if item.item_code != source_item.item_code or item.warehouse != source_item.warehouse:
			continue
		if frappe.utils.getdate(item.delivery_date) == delivery_date:
			return item


def _record_delivery_date_history(before_doc, after_doc, changes):
	version = frappe.new_doc("Version")
	if version.update_version_info(before_doc, after_doc):
		version.insert(ignore_permissions=True)

	lines = [_("Delivery dates changed from Sales Order Delivery Scheduling:")]
	for change in changes:
		line = _("{0}: {1} to {2}").format(
			frappe.bold(change["item_code"]),
			frappe.utils.formatdate(change["old_date"]),
			frappe.utils.formatdate(change["new_date"]),
		)
		if change.get("merged_to"):
			line = _("{0}; consolidated {1} qty into the existing {2} schedule").format(
				line,
				frappe.utils.flt(change.get("qty")),
				frappe.utils.formatdate(change["merged_to"]),
			)
		lines.append(line)
	after_doc.add_comment("Edit", "<br>".join(lines))


@frappe.whitelist()
def create_delivery_notes(so_details):
	_validate_scheduling_role()
	so_details = list(dict.fromkeys(frappe.parse_json(so_details)))
	if not so_details:
		frappe.throw(_("Select at least one Sales Order item."))
	locked_rows = _lock_sales_order_items(so_details)

	details_by_sales_order = {}
	for row in locked_rows:
		detail = row.name
		details_by_sales_order.setdefault(row.parent, []).append(detail)

	created = []
	from erpnext.selling.doctype.sales_order.sales_order import make_delivery_note
	for name, selected_details in details_by_sales_order.items():
		so = frappe.get_doc("Sales Order", name)
		available_qty = _validate_sales_order(so, selected_details)
		dn = make_delivery_note(name, kwargs={"filtered_children": selected_details})
		if not dn or not dn.get("items"):
			frappe.throw(_("No selected undelivered items are available for Sales Order {0}.").format(name))
		for item in dn.items:
			item.qty = frappe.utils.flt(available_qty[item.so_detail])
			item.amount = frappe.utils.flt(item.qty) * frappe.utils.flt(item.rate)
			item.base_amount = frappe.utils.flt(item.qty) * frappe.utils.flt(item.base_rate)
		dn.run_method("calculate_taxes_and_totals")
		from erpnext.stock.doctype.packed_item.packed_item import make_packing_list
		make_packing_list(dn)
		dn.custom_sales_order = name
		dn.workflow_state = "Draft"
		dn.insert()
		dn.db_set("workflow_state", "For Stock Confirmation")
		created.append(dn.name)
	return _("Created Delivery Note(s): {0}").format(", ".join(created))


def _validate_sales_order(so, selected_details):
	if so.docstatus != 1 or so.status != "To Deliver and Bill":
		frappe.throw(_("Sales Order {0} is not in To Deliver and Bill status.").format(so.name))
	if so.custom_so_type not in ("FOB", "FOB-DIRECT", "REGULAR"):
		frappe.throw(_("Sales Order {0} has an unsupported SO Type.").format(so.name))
	items = {item.name: item for item in so.items}
	available_qty = {}
	for detail in selected_details:
		item = items.get(detail)
		if not item:
			frappe.throw(_("Sales Order Item {0} does not belong to Sales Order {1}.").format(detail, so.name))
		if item.qty <= item.delivered_qty:
			frappe.throw(_("Sales Order Item {0} has no undelivered quantity.").format(detail))
		if item.warehouse and frappe.db.get_value("Warehouse", item.warehouse, "custom_is_province"):
			frappe.throw(_("Sales Order Item {0} belongs to provincial warehouse {1}.").format(detail, item.warehouse))
		_validate_sales_coordinator_access(so, item, require_transact=True)
		draft_qty = frappe.db.sql("""
			SELECT IFNULL(SUM(dni.qty), 0)
			FROM `tabDelivery Note Item` dni
			JOIN `tabDelivery Note` dn ON dn.name = dni.parent
			WHERE dni.so_detail = %s AND dn.docstatus = 0
		""", detail)[0][0]
		available = frappe.utils.flt(item.qty) - frappe.utils.flt(item.delivered_qty) - frappe.utils.flt(draft_qty)
		if available <= 0:
			frappe.throw(_("Sales Order Item {0} has no quantity available for another Delivery Note.").format(detail))
		available_qty[detail] = available
	return available_qty


def _get_draft_delivery_note_qty(so_detail):
	return frappe.utils.flt(frappe.db.sql("""
		SELECT IFNULL(SUM(dni.qty), 0)
		FROM `tabDelivery Note Item` dni
		JOIN `tabDelivery Note` dn ON dn.name = dni.parent
		WHERE dni.so_detail = %s AND dn.docstatus = 0
	""", so_detail)[0][0])


def _is_sales_coordinator():
	return "Sales Coordinator" in frappe.get_roles(frappe.session.user)


def _validate_scheduling_role():
	if frappe.session.user == "Administrator":
		return
	if not SCHEDULING_ROLES.intersection(frappe.get_roles(frappe.session.user)):
		frappe.throw(_("You are not allowed to manage Sales Order delivery scheduling."), frappe.PermissionError)


def _lock_sales_order_items(so_details):
	names = sorted(set(so_details))
	placeholders = ", ".join(["%s"] * len(names))
	rows = frappe.db.sql(
		f"""
		SELECT name, parent
		FROM `tabSales Order Item`
		WHERE name IN ({placeholders})
		ORDER BY name
		FOR UPDATE
		""",
		tuple(names),
		as_dict=True,
	)
	if len(rows) != len(names):
		found = {row.name for row in rows}
		missing = [name for name in names if name not in found]
		frappe.throw(_("Sales Order Item(s) not found: {0}").format(", ".join(missing)))
	return rows


def _apply_sales_coordinator_scope(conditions, values):
	if not _is_sales_coordinator():
		return

	user = frappe.session.user
	if has_territory_access(user):
		territories = get_user_allowed_territories(user)
		if not territories:
			conditions.append("1 = 0")
		else:
			conditions.append("so.territory IN %(allowed_territories)s")
			values["allowed_territories"] = tuple(territories)

	if _get_effective_warehouse_access_names(user, source="Role Profile"):
		warehouses = get_user_allowed_warehouses(
			user, require_list_view=True, source="Role Profile"
		)
		if not warehouses:
			conditions.append("1 = 0")
		else:
			conditions.append("soi.warehouse IN %(allowed_warehouses)s")
			values["allowed_warehouses"] = tuple(warehouses)


def _validate_sales_coordinator_access(so, item, require_transact=False):
	if not _is_sales_coordinator():
		return

	user = frappe.session.user
	if has_territory_access(user):
		territories = set(
			get_user_allowed_territories(user, require_transactions=require_transact)
		)
		if not so.territory or so.territory not in territories:
			frappe.throw(_("You are not allowed to transact in territory {0}.").format(so.territory), frappe.PermissionError)

	if _get_effective_warehouse_access_names(user, source="Role Profile"):
		warehouses = set(
			get_user_allowed_warehouses(
				user,
				require_transact=require_transact,
				require_list_view=not require_transact,
				source="Role Profile",
			)
		)
		if not item.warehouse or item.warehouse not in warehouses:
			frappe.throw(_("You are not allowed to transact in warehouse {0}.").format(item.warehouse), frappe.PermissionError)
