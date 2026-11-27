import json
import math
from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import flt, get_datetime


MSJR_STOCK_ENTRY_FIELDS = (
	"msjr_no",
	"custom_msrp_no",
	"custom_final_process",
	"custom_daily_job_report",
	"custom_rework_cycle",
)


def remove_msjr_stock_entry_integration():
	"""Remove obsolete MSJR fields and client behavior from Stock Entry."""
	for fieldname in MSJR_STOCK_ENTRY_FIELDS:
		name = f"Stock Entry-{fieldname}"
		if frappe.db.exists("Custom Field", name):
			frappe.delete_doc("Custom Field", name, ignore_permissions=True)

	script = "Stock Entry - MSJR No Field"
	if frappe.db.exists("Client Script", script):
		frappe.delete_doc("Client Script", script, ignore_permissions=True)

	frappe.clear_cache(doctype="Stock Entry")


def set_manufacture_actual_weight_uom(doc, method=None):
	"""Set default actual weight UOM on finished items in Manufacture stock entries."""
	if doc.purpose != "Manufacture":
		return
	
	default_uom = frappe.db.get_single_value("Stock Settings", "custom_default_actual_weight_uom")
	if not default_uom:
		return
	
	for item in (doc.get("items") or []):
		if item.is_finished_item and not item.custom_actual_weight_uom:
			item.custom_actual_weight_uom = default_uom


def _get_stock_entry_wh_code_warehouse_field(doc):
	"""Return the item warehouse field used to derive the WH Code."""
	if doc.get("purpose") in ("Material Issue", "Send to Subcontractor"):
		return "s_warehouse"
	if doc.get("purpose") in ("Material Receipt", "Manufacture"):
		return "t_warehouse"
	return None


def set_stock_entry_warehouse_code(doc, method=None):
	"""Set WH Code from the warehouse side implied by the selected Stock Entry Type."""
	warehouse_field = _get_stock_entry_wh_code_warehouse_field(doc)
	if not warehouse_field:
		return

	warehouses = {
		row.get(warehouse_field) for row in (doc.get("items") or []) if row.get(warehouse_field)
	}
	if warehouse_field == "t_warehouse" and doc.get("to_warehouse"):
		warehouses.add(doc.to_warehouse)

	if not warehouses:
		return

	if len(warehouses) > 1:
		frappe.throw(
			_("Stock Entry items must use one {0} so the WH Code can be determined.").format(
				_("Target Warehouse") if warehouse_field == "t_warehouse" else _("Source Warehouse")
			),
			title=_("Multiple Warehouses"),
		)

	warehouse = next(iter(warehouses))
	warehouse_code = frappe.db.get_value("Warehouse", warehouse, "custom_wh_code")
	if not warehouse_code:
		frappe.throw(
			_("{0} {1} has no WH Code configured.").format(
				_("Target Warehouse") if warehouse_field == "t_warehouse" else _("Source Warehouse"),
				frappe.bold(warehouse),
			),
			title=_("Warehouse Code Required"),
		)

	doc.custom_wh_code = warehouse_code


def validate_final_job_card_time_log(doc, method=None):
	if not _is_linked_manufacture_entry(doc):
		return

	job_card = frappe.get_doc("Job Card", doc.custom_final_job_card)
	if job_card.work_order != doc.work_order:
		frappe.throw(
			_("Final Job Card {0} does not belong to Work Order {1}.").format(
				frappe.bold(job_card.name),
				frappe.bold(doc.work_order),
			)
		)

	if doc.get("qcmc_output_allocations"):
		frappe.only_for(("Stock User", "Stock Manager", "Warehouse Checker"))
		return

	time_log_parent = frappe.db.get_value(
		"Job Card Time Log",
		doc.custom_job_card_time_log,
		"parent",
	)
	if time_log_parent != job_card.name:
		frappe.throw(
			_("Actual Time row {0} does not belong to Final Job Card {1}.").format(
				frappe.bold(doc.custom_job_card_time_log),
				frappe.bold(job_card.name),
			)
		)


def update_final_job_card_time_log_on_submit(doc, method=None):
	_update_final_job_card_manufactured_qty(doc)


def update_final_job_card_time_log_on_cancel(doc, method=None):
	_update_final_job_card_manufactured_qty(doc)


def _is_linked_manufacture_entry(doc):
	return bool(
		doc.purpose == "Manufacture"
		and doc.get("custom_final_job_card")
		and (doc.get("custom_job_card_time_log") or doc.get("qcmc_output_allocations"))
	)


def _update_final_job_card_manufactured_qty(doc):
	if not _is_linked_manufacture_entry(doc):
		return

	job_card = frappe.get_doc("Job Card", doc.custom_final_job_card)
	manufactured_qty = _get_final_job_card_manufactured_qty(job_card.name)
	job_card.db_set("manufactured_qty", manufactured_qty)
	job_card.manufactured_qty = manufactured_qty
	job_card.set_status(update_status=True)


def _get_final_job_card_manufactured_qty(job_card):
	stock_entries = frappe.get_all(
		"Stock Entry",
		filters={
			"purpose": "Manufacture",
			"docstatus": 1,
			"custom_final_job_card": job_card,
		},
		pluck="name",
	)
	if not stock_entries:
		return 0

	rows = frappe.get_all(
		"Stock Entry Detail",
		filters={
			"parent": ("in", stock_entries),
			"parenttype": "Stock Entry",
			"is_finished_item": 1,
		},
		fields=[{"SUM": "transfer_qty", "as": "qty"}],
	)
	return (rows and rows[0].qty) or 0


def lock_manufacture_work_order(work_order):
	if work_order:
		frappe.db.get_value("Work Order", work_order, "name", for_update=True)


def manufacture_reservations(work_order, exclude=None, lock=False):
	query = """select name, job_card, custom_final_job_card, custom_job_card_time_log,
	                  qcmc_output_allocations, fg_completed_qty
	           from `tabStock Entry`
	           where work_order = %s and purpose = 'Manufacture' and docstatus < 2
	                 and name != %s"""
	if lock:
		query += " for update"
		# The Work Order serializes these writes. On MariaDB installations with
		# snapshot isolation, read the latest reservations even if request
		# authentication opened a snapshot before the order lock was acquired.
		if frappe.db.db_type == "mariadb" and frappe.db.sql(
			"show session variables like 'innodb_snapshot_isolation'"
		):
			query = "set statement innodb_snapshot_isolation=off for " + query
	return frappe.db.sql(query, (work_order, exclude or ""), as_dict=True)


def _confirmed_intervals(job):
	return sorted(
		(row for row in job.time_logs if row.get("qcmc_output_confirmed_at") and flt(row.completed_qty) > 0),
		key=lambda row: (get_datetime(row.from_time), row.name),
	)


def _has_process_card(work_order):
	return bool(frappe.db.sql(
		"""select 1 from `tabProcess Card Job` link
		   join `tabProcess Card` card on card.name = link.parent
		   join `tabJob Card` job on job.name = link.job_card
		   where job.work_order = %s and card.status != 'Cancelled'
		   limit 1""", work_order,
	))


def _allocation_usage(job, reservations):
	usage = defaultdict(float)
	for entry in reservations:
		if not entry.custom_final_job_card and not entry.job_card and flt(entry.fg_completed_qty):
			frappe.throw(_("Reconcile the source interval for Manufacture Stock Entry {0}.").format(entry.name))
		if entry.custom_final_job_card != job.name:
			continue
		allocations = frappe.parse_json(entry.qcmc_output_allocations or "[]")
		if not allocations:
			frappe.throw(_("Reconcile the source interval for Manufacture Stock Entry {0}.").format(entry.name))
		for allocation in allocations:
			usage[allocation["time_log"]] += flt(allocation["qty"])
	return usage


def pending_confirmed_output(job, lock=False):
	reservations = manufacture_reservations(job.work_order, lock=lock)
	usage = _allocation_usage(job, reservations)
	return sum(max(flt(row.completed_qty) - usage[row.name], 0) for row in _confirmed_intervals(job))


def lock_manufacture_receipt(doc, method=None):
	if doc.purpose == "Manufacture":
		lock_manufacture_work_order(doc.work_order)


def allocate_confirmed_output(doc, method=None):
	"""Keep receipt reservations on their exact native production intervals."""
	previous = doc.get_doc_before_save()
	if previous and previous.get("qcmc_output_allocations") and any(
		previous.get(field) != doc.get(field)
		for field in ("purpose", "work_order", "custom_final_job_card")
	):
		frappe.throw(_("A reserved receipt cannot change its production source."))

	if doc.purpose != "Manufacture" or not doc.work_order:
		return

	lock_manufacture_work_order(doc.work_order)
	if not _has_process_card(doc.work_order):
		doc.qcmc_output_allocations = None
		return

	work_order = frappe.get_doc("Work Order", doc.work_order, for_update=True)
	if doc.get("job_card") and work_order.track_semi_finished_goods:
		source = frappe.db.get_value("Job Card", doc.job_card, ["work_order", "finished_good"], as_dict=True)
		if source and source.work_order == work_order.name and source.finished_good not in (None, "", work_order.production_item):
			return

	from qcmc_logic.api.stock_entry import _validate_final_operation_job_card

	if not doc.get("custom_final_job_card"):
		frappe.throw(_("Select a confirmed final-operation Job Card to receive this Work Order."))

	job = frappe.get_doc("Job Card", doc.custom_final_job_card, for_update=True)
	if (
		job.work_order != work_order.name
		or job.docstatus == 2
		or job.is_corrective_job_card
		or job.finished_good
	):
		frappe.throw(_("Select an active final-operation Job Card belonging to this Work Order."))
	_validate_final_operation_job_card(job, work_order)

	precision = doc.precision("fg_completed_qty")
	finished = [row for row in doc.items if row.is_finished_item and row.item_code == work_order.production_item]
	quantity = flt(sum(flt(row.transfer_qty) for row in finished), precision)
	if not math.isfinite(quantity) or quantity <= 0:
		frappe.throw(_("Enter a positive finished goods receipt quantity."))
	if quantity != flt(doc.fg_completed_qty, precision) or flt(doc.process_loss_qty):
		frappe.throw(_("Finished goods rows must match the receipt quantity with zero process loss."))

	reservations = manufacture_reservations(work_order.name, doc.name, lock=True)
	reserved = sum(flt(row.fg_completed_qty) for row in reservations if not row.job_card)
	if flt(quantity + reserved, precision) > flt(work_order.qty, precision):
		frappe.throw(_("Draft and submitted manufacture quantities exceed the Work Order quantity."))

	usage = _allocation_usage(job, reservations)
	old = frappe.parse_json((previous and previous.get("qcmc_output_allocations")) or "[]")
	intervals = {row.name: row for row in _confirmed_intervals(job)}
	allocated = {}
	remaining = quantity
	# Preserve prior intervals when a draft is resized, even if earlier capacity
	# was released by a different receipt.
	sources = [(intervals.get(row["time_log"]), flt(row["qty"])) for row in old]
	sources.extend((row, flt(row.completed_qty)) for row in intervals.values())
	for row, requested in sources:
		if remaining <= 0:
			break
		if not row:
			frappe.throw(_("A previously reserved production interval is no longer available."))
		unreserved = flt(row.completed_qty) - usage[row.name] - allocated.get(row.name, 0)
		take = flt(min(requested, unreserved, remaining), precision)
		if take > 0:
			allocated[row.name] = flt(allocated.get(row.name, 0) + take, precision)
			remaining = flt(remaining - take, precision)

	if remaining > 0:
		frappe.throw(_("Receipt exceeds unreserved confirmed output by {0}.").format(remaining))

	doc.qcmc_output_allocations = json.dumps([
		{"process_card": intervals[name].qcmc_process_card, "time_log": name, "qty": qty}
		for name, qty in allocated.items()
	])
	doc.custom_job_card_time_log = next(iter(allocated)) if len(allocated) == 1 else None
