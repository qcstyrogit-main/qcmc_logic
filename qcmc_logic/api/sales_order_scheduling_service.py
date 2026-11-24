"""Business services used by the Sales Order Delivery Scheduling workbench.

The Query Report module is a deprecated compatibility surface only. Workbench
queries and actions are owned by this API/service module.
"""

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
	date_operator = "<=" if frappe.utils.cint(filters.get("include_overdue")) else "="
	if filters.get("warehouse"):
		conditions.append("s.warehouse = %(warehouse)s")
		values["warehouse"] = filters.warehouse
	_apply_sales_coordinator_scope(conditions, values)
	rows = frappe.db.sql("""
		SELECT s.name AS schedule_id, s.name AS schedule, soi.name AS so_detail,
			so.name AS sales_order, so.customer_name, so.custom_so_type AS so_type,
			soi.item_code, soi.item_name, s.warehouse,
			CASE WHEN s.history_status = 'Verified' THEN s.current_total ELSE s.planned_qty END AS qty,
			soi.uom, IFNULL(submitted.qty, 0) AS delivered_qty,
			GREATEST(soi.qty - soi.delivered_qty, 0) AS balance_qty,
			IFNULL(draft.qty, 0) AS draft_dr_qty,
			GREATEST(CASE WHEN s.history_status = 'Verified' THEN s.current_total ELSE s.planned_qty END
				- IFNULL(submitted.qty, 0) - IFNULL(draft.qty, 0), 0) AS available_qty,
			IFNULL(bin.actual_qty, 0) AS actual_qty, s.delivery_date,
			CAST(s.delivery_date AS CHAR) AS delivery_dates, s.delivery_date AS available_from,
			s.modified AS schedule_modified, s.history_status,
			s.final_qty, s.confirmation_status
		FROM `tabSO Delivery Schedule` s
		JOIN `tabSales Order` so ON so.name = s.sales_order
		JOIN `tabSales Order Item` soi ON soi.name = s.sales_order_item AND soi.parent = so.name
		JOIN `tabWarehouse` wh ON wh.name = s.warehouse
		LEFT JOIN `tabBin` bin ON bin.item_code = s.item_code AND bin.warehouse = s.warehouse
		LEFT JOIN (
			SELECT dni.custom_so_delivery_schedule AS schedule, SUM(dni.qty) AS qty
			FROM `tabDelivery Note Item` dni JOIN `tabDelivery Note` dn ON dn.name = dni.parent
			WHERE dn.docstatus = 0 AND dni.custom_so_delivery_schedule IS NOT NULL
			GROUP BY dni.custom_so_delivery_schedule
		) draft ON draft.schedule = s.name
		LEFT JOIN (
			SELECT dni.custom_so_delivery_schedule AS schedule, SUM(dni.qty) AS qty
			FROM `tabDelivery Note Item` dni JOIN `tabDelivery Note` dn ON dn.name = dni.parent
			WHERE dn.docstatus = 1 AND dni.custom_so_delivery_schedule IS NOT NULL
			GROUP BY dni.custom_so_delivery_schedule
		) submitted ON submitted.schedule = s.name
		WHERE so.docstatus = 1 AND so.status IN ('To Deliver and Bill', 'To Deliver', 'To Bill')
			AND so.custom_so_type = 'REGULAR'
			AND IFNULL(wh.custom_is_province, 0) = 0
			AND GREATEST(soi.qty - soi.delivered_qty, 0) > 0
			AND s.delivery_date {date_operator} %(delivery_date)s
			AND {conditions}
		ORDER BY s.delivery_date, so.name, soi.idx, s.name
	""".format(conditions=" AND ".join(conditions), date_operator=date_operator), values, as_dict=True)
	rows = [row for row in rows if row.history_status != "Verified" or row.available_qty > 0]
	rows.sort(key=lambda row: (str(row.available_from), row.sales_order, row.schedule_id))
	return columns, rows, _("{0} eligible schedule(s) found.").format(len(rows)), None, _build_scheduling_kpis(rows, filters)

def _build_scheduling_kpis(rows, filters):
	selected = [row for row in rows if str(row.available_from) == str(filters.delivery_date)]
	overdue = [row for row in rows if str(row.available_from) < str(filters.delivery_date)]
	def quantity_label(group):
		by_uom = {}
		for row in group:
			by_uom[row.uom] = by_uom.get(row.uom, 0) + frappe.utils.flt(row.available_qty)
		return ", ".join("{0:g} {1}".format(qty, uom) for uom, qty in sorted(by_uom.items())) or "0"
	values = []
	if frappe.utils.cint(filters.get("include_overdue")):
		values.extend([
			{"value": len({row.sales_order for row in selected}), "indicator": "Blue", "label": _("Pending SOs · Selected Date"), "datatype": "Int"},
			{"value": len(selected), "indicator": "Green", "label": _("Schedule Items · Selected Date"), "datatype": "Int"},
			{"value": quantity_label(selected), "indicator": "Orange", "label": _("Remaining Qty · Selected Date"), "datatype": "Data"},
			{"value": len({row.sales_order for row in overdue}), "indicator": "Blue", "label": _("Pending SOs · Overdue"), "datatype": "Int"},
			{"value": len(overdue), "indicator": "Green", "label": _("Schedule Items · Overdue"), "datatype": "Int"},
			{"value": quantity_label(overdue), "indicator": "Red", "label": _("Remaining Qty · Overdue"), "datatype": "Data"},
		])
	else:
		values.extend([
			{"value": len({row.sales_order for row in selected}), "indicator": "Blue", "label": _("Pending Sales Orders"), "datatype": "Int"},
			{"value": len(selected), "indicator": "Green", "label": _("Pending Schedule Items"), "datatype": "Int"},
			{"value": quantity_label(selected), "indicator": "Orange", "label": _("Remaining Schedulable Qty"), "datatype": "Data"},
		])
	details = [row.schedule_id for row in selected]
	created_count = 0
	if details:
		created_count = frappe.db.sql("""
			SELECT COUNT(DISTINCT dn.name) FROM `tabDelivery Note` dn
			JOIN `tabDelivery Note Item` dni ON dni.parent = dn.name
			WHERE dn.docstatus = 0 AND dni.custom_so_delivery_schedule IN %(details)s
		""", {"details": tuple(details)})[0][0]
	values.append({"value": created_count, "indicator": "Purple", "label": _("DRs Created · Selected Date"), "datatype": "Int"})
	return values


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
	"""Retired Sales Order Item schedule lookup; use SO Delivery Schedule records."""
	frappe.throw(_("Sales Order Item split scheduling is retired. Use SO Delivery Schedule records."))


@frappe.whitelist()
def adjust_scheduled_quantity(source_so_detail, target_so_detail, new_qty, remarks=None):
	"""Retired: schedule quantity changes belong to SO Delivery Schedule records."""
	frappe.throw(_("Use Delivery Schedule Workbench to move scheduled quantities."))


@frappe.whitelist()
def cleanup_zero_schedules(sales_order):
	"""Retired: operational scheduling never deletes or splits Sales Order Items."""
	frappe.throw(_("Sales Order Items are not modified by delivery scheduling."))


def _can_remove_schedule_item(item):
	# Preserve row identities even for cancelled/zero-quantity historical links.
	# Several ERPNext references are Data fields and escape normal Link checks.
	for doctype, fieldname in (
		("Delivery Note Item", "so_detail"), ("Sales Invoice Item", "so_detail"),
		("Work Order", "sales_order_item"), ("Pick List Item", "sales_order_item"),
		("Purchase Order Item", "sales_order_item"), ("Material Request Item", "sales_order_item"),
		("Production Plan Item", "sales_order_item"), ("Delivery Schedule Item", "sales_order_item"),
		("Stock Reservation Entry", "voucher_detail_no"),
	):
		if frappe.db.exists(doctype, {fieldname: item.name}):
			return False
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


@frappe.whitelist()
def update_delivery_dates(so_details, delivery_date):
	"""Retired: dates are owned by SO Delivery Schedule records."""
	frappe.throw(_("Use Schedule Deliveries to edit delivery dates."))


@frappe.whitelist()
def get_consolidation_candidates(so_details):
	"""Retired legacy DN consolidation lookup; consolidate only finalized schedule allocations."""
	frappe.throw(_("Delivery Note candidates must be selected from finalized delivery schedules."))


@frappe.whitelist()
def get_creation_preview(so_details):
	"""Retired legacy preview; preview finalized schedule allocations instead."""
	frappe.throw(_("Use the Delivery Schedule Workbench to preview finalized schedules."))


@frappe.whitelist()
def create_delivery_notes(so_details, consolidate_into=None, requested_quantities=None):
	"""Retired: Delivery Notes may only be created from finalized SO Delivery Schedules."""
	frappe.throw(_("Use Proceed to DR from finalized delivery schedules."))


def _validate_compatible_consolidation(target, incoming, sales_order, delivery_date):
	if target.docstatus != 0 or target.workflow_state != "For Stock Confirmation":
		frappe.throw(_("Only unreleased Delivery Notes awaiting stock confirmation can be consolidated."))
	if target.company != incoming.company or target.customer != incoming.customer:
		frappe.throw(_("The existing Delivery Note must have the same company and customer."))
	if target.shipping_address_name != incoming.shipping_address_name:
		frappe.throw(_("The existing Delivery Note must have the same delivery address."))
	for field in ("currency", "conversion_rate", "selling_price_list", "taxes_and_charges", "tc_name", "terms", "customer_address"):
		if target.get(field) != incoming.get(field):
			frappe.throw(_("Delivery Note terms differ ({0}); create a separate DR.").format(field))
	if target.get("is_return") or target.get("custom_dr_number") or frappe.db.exists("Sales Invoice Item", {"delivery_note": target.name, "docstatus": ["<", 2]}):
		frappe.throw(_("A returned, numbered, or invoiced DR cannot receive additional items."))
	if any(item.against_sales_order != sales_order for item in target.items):
		frappe.throw(_("Consolidation is limited to Delivery Notes for the same Sales Order."))
	if any(str(frappe.db.get_value("Sales Order Item", item.so_detail, "custom_next_scheduling_date") or frappe.db.get_value("Sales Order Item", item.so_detail, "delivery_date")) != str(delivery_date) for item in target.items):
		frappe.throw(_("The existing Delivery Note must have the same scheduled delivery date."))
	if {item.warehouse for item in target.items} != {item.warehouse for item in incoming.items}:
		frappe.throw(_("The existing Delivery Note must use the same warehouse as the added items."))


def _reset_new_item_logistics_confirmation(item):
	for fieldname in ("custom_logistics_reason", "custom_logistics_remarks", "custom_logistics_proposed_date"):
		if item.meta.has_field(fieldname):
			item.set(fieldname, None)
	if item.meta.has_field("custom_logistics_proposed_qty"):
		item.custom_logistics_proposed_qty = 0


def _validate_sales_order(so, selected_details):
	from qcmc_logic.api.sales_order_delivery_eligibility import is_open_sales_order_for_delivery
	if not is_open_sales_order_for_delivery(so):
		frappe.throw(_("Sales Order {0} is not open for delivery.").format(so.name))
	if so.custom_so_type not in ("REGULAR",):
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
	if not names:
		return []
	from qcmc_logic.api.sales_order_schedule_split import lock_orders
	parents = frappe.get_all("Sales Order Item", filters={"name": ["in", names]}, pluck="parent")
	lock_orders(parents)
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
