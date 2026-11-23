import json
from datetime import timedelta

import frappe
from frappe import _
from frappe.utils import flt

from qcmc_logic.qcmc_logics.doctype.process_card.process_card import ALLOWED_TRANSITIONS


MAX_JOB_CARDS_PER_SEARCH = 50
MAX_JOB_CARDS_PER_REQUEST = 100
MAX_BATCH_PROCESS_CARDS = 250
MAX_BATCH_OUTPUT_ROWS = 500


def _company_access(company):
	if not company or not frappe.get_list("Company", filters={"name": company}, pluck="name", limit_page_length=1):
		frappe.throw(_("You do not have access to this Process Card Company."), frappe.PermissionError)


def _process_card(name, permission="read"):
	if not name or not frappe.db.exists("Process Card", name):
		frappe.throw(_("Process Card not found."), frappe.DoesNotExistError)
	card = frappe.get_doc("Process Card", name)
	card.check_permission(permission)
	_company_access(card.company)
	site = None
	if card.site and frappe.db.exists("Production Site", card.site):
		site = frappe.get_doc("Production Site", card.site)
		site.check_permission("read")
		if site.company != card.company:
			frappe.throw(_("Process Card Site does not belong to its Company."), frappe.PermissionError)
	if card.workstation:
		workstation = frappe.get_doc("Workstation", card.workstation)
		workstation.check_permission("read")
		if workstation.disabled:
			frappe.throw(_("The Process Card Workstation is disabled."))
		if workstation.plant_floor:
			floor = frappe.db.get_value("Plant Floor", workstation.plant_floor, ["name", "company"], as_dict=True)
			if floor and floor.company != card.company:
				frappe.throw(_("Process Card Workstation belongs to a different Company."), frappe.PermissionError)
		if site:
			if workstation.plant_floor and workstation.plant_floor not in {row.plant_floor for row in site.plant_floors}:
				frappe.throw(_("Process Card Workstation is outside its Production Site."), frappe.PermissionError)
		elif card.site and workstation.plant_floor and card.site != workstation.plant_floor:
			frappe.throw(_("Process Card Workstation is outside its Plant Floor."), frappe.PermissionError)
	return card


def _job_card(name, company, workstation, allow_historical=False):
	if not frappe.db.exists("Job Card", name):
		frappe.throw(_("Job Card {0} does not exist or is cancelled.").format(name))
	job = frappe.get_doc("Job Card", name)
	job.check_permission("read")
	if job.docstatus == 2 or job.status == "Cancelled":
		frappe.throw(_("Job Card {0} does not exist or is cancelled.").format(name))
	if job.status == "Completed" and not allow_historical:
		frappe.throw(_("Job Card {0} is already completed.").format(name))
	if job.company != company or job.workstation != workstation:
		frappe.throw(_("Job Card {0} must match the Process Card Company and Workstation.").format(name))
	if not job.work_order or not frappe.db.exists("Work Order", job.work_order):
		frappe.throw(_("Job Card {0} must belong to a submitted Work Order.").format(name))
	work_order = frappe.get_doc("Work Order", job.work_order)
	work_order.check_permission("read")
	if (
		work_order.docstatus != 1
		or work_order.status == "Cancelled"
		or (not allow_historical and work_order.status in {"Stopped", "Completed"})
	):
		frappe.throw(_("Job Card {0} must belong to a submitted Work Order.").format(name))
	if work_order.company != company:
		frappe.throw(_("Job Card {0} Work Order belongs to a different Company.").format(name))
	has_operations = frappe.db.exists("Work Order Operation", {"parent": job.work_order})
	if job.operation_id:
		if not frappe.db.exists(
			"Work Order Operation",
			{"name": job.operation_id, "parent": job.work_order, "operation": job.operation},
		):
			frappe.throw(_("Job Card {0} operation is not part of its Work Order.").format(name))
	elif has_operations:
		frappe.throw(_("Job Card {0} must identify its Work Order operation.").format(name))
	return job, work_order


def _job_card_payload(job):
	return {
		"name": job.name,
		"status": job.status,
		"docstatus": job.docstatus,
		"work_order": job.work_order,
		"operation": job.operation,
		"operation_id": job.operation_id,
		"production_item": job.production_item,
		"for_quantity": job.for_quantity,
		"total_completed_qty": job.total_completed_qty,
		"actual_start_date": job.actual_start_date,
		"actual_end_date": job.actual_end_date,
	}


def _job_output_standards(job):
	"""Resolve the saved Work Order operation SOPH; packing operations use their pack rate."""
	operation = None
	if job.operation_id and frappe.db.exists("Work Order Operation", job.operation_id):
		operation = frappe.get_doc("Work Order Operation", job.operation_id)
	if not operation and job.work_order and job.operation:
		rows = frappe.get_list(
			"Work Order Operation", parent_doctype="Work Order",
			filters={"parent": job.work_order, "parenttype": "Work Order", "operation": job.operation},
			fields=["name"], limit_page_length=1,
		)
		if rows:
			operation = frappe.get_doc("Work Order Operation", rows[0].name)
	soph = flt(operation.get("custom_pack_soph")) if operation and "pack" in (job.operation or "").lower() else 0
	if not soph and operation:
		soph = flt(operation.get("custom_soph"))
	if not soph and job.work_order:
		bom_no = frappe.db.get_value("Work Order", job.work_order, "bom_no")
		bom_access = True
		if bom_no:
			try:
				bom = frappe.get_doc("BOM", bom_no)
				bom.check_permission("read")
				soph = flt(bom.get("custom_pack_soph")) if "pack" in (job.operation or "").lower() else 0
			except frappe.PermissionError:
				bom_access = False
		if not soph and bom_no and bom_access:
			soph = flt(frappe.db.get_value("BOM", bom_no, "custom_soph"))
	output_item = (operation.get("custom_eps_output_item") if operation else None) or job.production_item
	item_rows = frappe.get_list(
		"Item", filters={"name": output_item}, fields=["custom_number_of_color"], limit_page_length=1,
	) if output_item else []
	item_color_count = item_rows[0].custom_number_of_color if item_rows else None
	return {"soph": soph or None, "color_count": item_color_count, "output_item": output_item}


def _output_calculation(good_qty, rejected_qty, soph, period_minutes):
	from decimal import Decimal, InvalidOperation

	try:
		good = Decimal(str(good_qty))
		rejected = Decimal(str(rejected_qty or 0))
		rate = Decimal(str(soph))
		minutes = Decimal(str(period_minutes))
	except (InvalidOperation, TypeError, ValueError):
		frappe.throw(_("Output, SOPH, and period must be valid numbers."))
	if not all(value.is_finite() for value in (good, rejected, rate, minutes)) or good < 0 or rejected < 0 or minutes < 0:
		frappe.throw(_("Output and period must be finite nonnegative values."))
	if rate < 0:
		frappe.throw(_("SOPH must be greater than zero."))
	if rate <= 0:
		return {"soph": float(rate), "run_hours": None, "remaining_minutes": None, "soph_available": False, "negative_remaining": False}
	run_hours = (good + rejected) / rate
	remaining = minutes - run_hours * 60
	return {
		"soph": float(rate), "run_hours": round(float(run_hours), 3),
		"remaining_minutes": round(float(remaining), 1), "soph_available": True,
		"negative_remaining": remaining < 0,
	}


def _new_card_context(company, site_name, workstation_name):
	"""Validate floor context and return only records the current user may use."""
	if not frappe.has_permission("Process Card", "create"):
		frappe.throw(_("You do not have permission to create Process Cards."), frappe.PermissionError)
	_company_access(company)
	if not site_name or not frappe.db.exists("Production Site", site_name):
		frappe.throw(_("Select an accessible Production Site."), frappe.PermissionError)
	site = frappe.get_doc("Production Site", site_name)
	site.check_permission("read")
	if site.company != company:
		frappe.throw(_("Production Site does not belong to the selected Company."), frappe.PermissionError)
	workstation = frappe.get_doc("Workstation", workstation_name)
	workstation.check_permission("read")
	if workstation.disabled:
		frappe.throw(_("Select an enabled Workstation."))
	if workstation.plant_floor and workstation.plant_floor not in {row.plant_floor for row in site.plant_floors}:
		frappe.throw(_("Workstation is outside the selected Production Site."), frappe.PermissionError)
	return site, workstation


def _eligible_creation_job_cards(company, workstation, search=None):
	filters = {
		"company": company,
		"workstation": workstation,
		"docstatus": ["!=", 2],
		"status": ["not in", ["Completed", "Cancelled"]],
	}
	or_filters = None
	search = (search or "").strip()
	if search:
		pattern = f"%{search[:100]}%"
		or_filters = [
			["Job Card", "name", "like", pattern],
			["Job Card", "work_order", "like", pattern],
			["Job Card", "operation", "like", pattern],
			["Job Card", "production_item", "like", pattern],
		]
	rows = frappe.get_list(
		"Job Card", filters=filters, or_filters=or_filters,
		fields=["name", "work_order", "operation", "operation_id", "production_item", "for_quantity", "total_completed_qty", "status", "docstatus"],
		limit_page_length=MAX_JOB_CARDS_PER_SEARCH, order_by="modified desc",
	)
	work_order_names = sorted({row.work_order for row in rows if row.work_order})
	work_orders = frappe.get_list(
		"Work Order",
		filters={
			"name": ["in", work_order_names],
			"company": company,
			"docstatus": 1,
			"status": ["not in", ["Stopped", "Completed", "Cancelled"]],
		},
		fields=["name"], limit_page_length=MAX_JOB_CARDS_PER_SEARCH,
	) if work_order_names else []
	valid_work_orders = {row.name for row in work_orders}
	operations = frappe.get_list(
		"Work Order Operation", parent_doctype="Work Order",
		filters={"parent": ["in", sorted(valid_work_orders)], "parenttype": "Work Order"},
		fields=["name", "parent", "operation"], limit_page_length=MAX_JOB_CARDS_PER_SEARCH * 10,
	) if valid_work_orders else []
	valid_operations = {(row.name, row.parent, row.operation) for row in operations}
	work_orders_with_operations = {row.parent for row in operations}
	return [
		row for row in rows
		if row.work_order in valid_work_orders
		and (
			(row.operation_id, row.work_order, row.operation) in valid_operations
			or (
				not row.operation_id
				and not row.operation
				and row.work_order not in work_orders_with_operations
			)
		)
	]


@frappe.whitelist(methods=["GET"])
def get_process_card_creation_context(company, site, workstation, shift_date, shift_type=None, search=None):
	"""Load authorized shift types and eligible Job Cards for Workbench creation."""
	production_site, workstation_doc = _new_card_context(company, site, workstation)
	shift_types = frappe.get_list(
		"Shift Type", fields=["name", "start_time", "end_time"], limit_page_length=0, order_by="name asc",
	)
	if shift_type and shift_type not in {row.name for row in shift_types}:
		frappe.throw(_("Shift Type is unavailable."), frappe.PermissionError)
	return {
		"company": production_site.company,
		"site": production_site.name,
		"workstation": {
			"name": workstation_doc.name,
			"workstation_name": workstation_doc.workstation_name or workstation_doc.name,
			"plant_floor": workstation_doc.plant_floor,
		},
		"shift_date": shift_date,
		"shift_types": shift_types,
		"job_cards": _eligible_creation_job_cards(company, workstation, search),
	}


@frappe.whitelist(methods=["POST"])
def create_process_card(company, site, workstation, shift_date, shift_type, shift_start, shift_end, job_cards, remarks=None):
	"""Create a Process Card and allocate explicitly selected Job Cards in one save."""
	try:
		names = frappe.parse_json(job_cards) if isinstance(job_cards, str) else job_cards
	except (TypeError, ValueError):
		frappe.throw(_("Select valid Job Cards."))
	if not isinstance(names, list) or not names or len(names) > MAX_JOB_CARDS_PER_REQUEST:
		frappe.throw(_("Select between one and {0} Job Cards before creating the Process Card.").format(MAX_JOB_CARDS_PER_REQUEST))
	if any(not isinstance(name, str) or not name.strip() for name in names) or len(names) != len(set(names)):
		frappe.throw(_("Each Job Card can only be selected once."))
	production_site, workstation_doc = _new_card_context(company, site, workstation)
	shift_types = frappe.get_list("Shift Type", filters={"name": shift_type}, fields=["name"], limit_page_length=1)
	if not shift_types:
		frappe.throw(_("Select an accessible Shift Type."), frappe.PermissionError)
	card = frappe.new_doc("Process Card")
	card.company = production_site.company
	card.site = production_site.name
	card.workstation = workstation_doc.name
	card.shift_date = shift_date
	card.shift_type = shift_type
	card.shift_start = shift_start
	card.shift_end = shift_end
	card.remarks = (remarks or "").strip()
	for name in names:
		job, work_order = _job_card(name, card.company, card.workstation)
		card.append("jobs", {
			"job_card": job.name, "work_order": work_order.name,
			"operation": job.operation, "production_item": job.production_item,
		})
	card.insert()
	return {"name": card.name, "status": card.status}


def _checkpoint_intervals(card):
	"""Build schedule slots from actual Process Card bounds and Shift Type config."""
	from frappe.utils import get_datetime

	configured = frappe.db.get_value("Shift Type", card.shift_type, "qcmc_checkpoint_interval_minutes")
	interval_minutes = 120 if configured in (None, "") else int(configured)
	if interval_minutes < 1:
		frappe.throw(_("Shift Type checkpoint interval must be at least one minute."))
	start, end = get_datetime(card.shift_start), get_datetime(card.shift_end)
	rows = []
	while start < end:
		checkpoint_end = min(start + timedelta(minutes=interval_minutes), end)
		rows.append({"from_time": str(start), "to_time": str(checkpoint_end), "entries": [], "missing_job_cards": []})
		start = checkpoint_end
	return rows, interval_minutes


def _production_output_summary(card, job_docs):
	from qcmc_logic.api.job_card_time_log import _checkpoint_output_rows, _operational_output_row

	checkpoints, interval_minutes = _checkpoint_intervals(card)
	checkpoint_by_key = {(row["from_time"], row["to_time"]): row for row in checkpoints}
	standards_by_job = {job.name: _job_output_standards(job) for job in job_docs}
	items = {standards_by_job[job.name]["output_item"] for job in job_docs if standards_by_job[job.name]["output_item"]}
	item_rows = frappe.get_list(
		"Item", filters={"name": ["in", sorted(items)]},
		fields=["name", "stock_uom", "item_name"], limit_page_length=0,
	) if items else []
	item_uoms = {row.name: row.stock_uom for row in item_rows}
	item_descriptions = {row.name: row.item_name for row in item_rows}
	per_job = []
	per_item = {}
	for job in job_docs:
		entries = _checkpoint_output_rows(job, card.name)
		standards = standards_by_job[job.name]
		output_item = standards["output_item"]
		uom = item_uoms.get(output_item, "")
		good = sum(row["good_qty"] for row in entries)
		rejected = sum(row["rejected_qty"] for row in entries)
		all_operational_entries = [
			_operational_output_row(time_log)
			for time_log in (job.get("time_logs") or [])
			if time_log.get("qcmc_process_card")
			and int(time_log.get("qcmc_output_revision") or 0) > 0
		]
		all_operational_qty = sum(row["good_qty"] + row["rejected_qty"] for row in all_operational_entries)
		target_qty = flt(job.for_quantity)
		official_completed_qty = flt(job.total_completed_qty)
		job_summary = {
			"job_card": job.name, "production_item": output_item, "uom": uom,
			"product_description": item_descriptions.get(output_item, ""),
			"good_qty": good, "rejected_qty": rejected, "recorded_qty": good + rejected,
			"target_qty": target_qty, "official_completed_qty": official_completed_qty,
			"current_process_card_output_qty": good + rejected,
			"all_process_card_good_qty": sum(row["good_qty"] for row in all_operational_entries),
			"all_process_card_rejected_qty": sum(row["rejected_qty"] for row in all_operational_entries),
			"all_process_card_output_qty": all_operational_qty,
			"remaining_qty": max(target_qty - official_completed_qty - all_operational_qty, 0),
			# Kept temporarily for older clients; now uses the cross-Process-Card remainder.
			"good_balance_qty": max(target_qty - official_completed_qty - all_operational_qty, 0),
			"soph": standards["soph"], "color_count": standards["color_count"],
			"entries": entries,
		}
		per_job.append(job_summary)
		key = (output_item, uom)
		total = per_item.setdefault(key, {"production_item": key[0], "uom": key[1], "good_qty": 0, "rejected_qty": 0, "recorded_qty": 0})
		total["good_qty"] += good
		total["rejected_qty"] += rejected
		total["recorded_qty"] += good + rejected
		for entry in entries:
			key = (entry["from_time"], entry["to_time"])
			if key not in checkpoint_by_key:
				checkpoint = {"from_time": entry["from_time"], "to_time": entry["to_time"], "entries": [], "missing_job_cards": [], "historical": True}
				checkpoints.append(checkpoint)
				checkpoint_by_key[key] = checkpoint
			checkpoint_by_key[key]["entries"].append({
				"job_card": job.name, "production_item": output_item, "uom": uom,
				"good_qty": entry["good_qty"], "rejected_qty": entry["rejected_qty"],
				"remarks": entry["remarks"], "entered_at": entry["entered_at"], "entered_by": entry["entered_by"],
				"correction_history": entry["correction_history"],
				"time_log_id": entry["time_log_id"], "revision": entry["revision"],
			})
	for checkpoint in checkpoints:
		entry_job_cards = {entry["job_card"] for entry in checkpoint["entries"]}
		checkpoint["missing_job_cards"] = [job.name for job in job_docs if job.name not in entry_job_cards]
		checkpoint["complete"] = not checkpoint["missing_job_cards"]
	checkpoints.sort(key=lambda row: row["from_time"])
	return {
		"checkpoint_interval_minutes": interval_minutes,
		"checkpoints": checkpoints,
		"per_job": per_job,
		"per_item": list(per_item.values()),
	}


@frappe.whitelist(methods=["GET"])
def get_batch_output_context(site, shift_date, shift_type=None, building=None):
	"""List output-eligible linked Job Cards in Process Cards for one authorized site and shift."""
	if not shift_type or not frappe.get_list("Shift Type", filters={"name": shift_type}, fields=["name"], limit_page_length=1):
		frappe.throw(_("Select an accessible Shift Type."), frappe.PermissionError)
	if not frappe.db.exists("Production Site", site):
		frappe.throw(_("Production Site is unavailable."), frappe.PermissionError)
	production_site = frappe.get_doc("Production Site", site)
	production_site.check_permission("read")
	layouts = frappe.get_list("Production Floor Layout", filters={"production_site": site}, fields=["layout_json"], limit_page_length=1)
	workstations = None
	if building:
		workstations = set()
		if layouts:
			try:
				layout = json.loads(layouts[0].layout_json or "{}")
			except (TypeError, ValueError):
				layout = {}
			for row in layout.get("buildings", []):
				if building in {row.get("id"), row.get("label")}:
					workstations.update(
						element.get("workstation") for element in row.get("interior", {}).get("elements", [])
						if element.get("kind") == "machine" and element.get("workstation")
					)
					break
	filters = {"site": site, "shift_date": shift_date, "status": ["in", ["Draft", "In Progress"]]}
	if shift_type:
		filters["shift_type"] = shift_type
	cards = frappe.get_list("Process Card", filters=filters, fields=["name", "workstation"], limit_page_length=MAX_BATCH_PROCESS_CARDS + 1, order_by="workstation asc, name asc")
	if len(cards) > MAX_BATCH_PROCESS_CARDS:
		frappe.throw(_("More than {0} Process Cards match. Narrow the selected site, building, or shift.").format(MAX_BATCH_PROCESS_CARDS))
	result = []
	for row in cards:
		if workstations is not None and row.workstation not in workstations:
			continue
		try:
			context = get_process_card_context(row.name)
		except (frappe.PermissionError, frappe.DoesNotExistError):
			continue
		card = context["process_card"]
		if not context["can_record_output"]:
			continue
		for job in context["job_cards"]:
			if job["docstatus"] or job["status"] == "Cancelled":
				continue
			try:
				job_write = bool(job.get("can_record_output")) and bool(
					frappe.has_permission("Job Card", "write", doc=frappe.get_doc("Job Card", job["name"]))
				)
			except (frappe.PermissionError, frappe.DoesNotExistError):
				job_write = False
			operational = next((entry for entry in context["production_output"]["per_job"] if entry["job_card"] == job["name"]), {})
			result.append({
				"process_card": card["name"], "process_card_status": card["status"],
				"job_card": job["name"], "work_order": job["work_order"], "operation": job["operation"] or job["operation_id"],
				"product_code": operational.get("production_item") or job["production_item"], "product_description": operational.get("product_description", ""),
				"uom": operational.get("uom", ""), "workstation": card["workstation_name"], "building": card["building"],
				"soph": operational.get("soph"), "color_count": operational.get("color_count"),
				"target_qty": operational.get("target_qty", job.get("for_quantity", 0)),
				"official_completed_qty": operational.get("official_completed_qty", job.get("total_completed_qty", 0)),
				"all_process_card_good_qty": operational.get("all_process_card_good_qty", 0),
				"all_process_card_rejected_qty": operational.get("all_process_card_rejected_qty", 0),
				"all_process_card_output_qty": operational.get("all_process_card_output_qty", 0),
				"current_process_card_output_qty": operational.get("current_process_card_output_qty", 0),
				"remaining_qty": operational.get("remaining_qty", 0),
				"from_time": str(card["shift_start"]), "to_time": str(card["shift_end"]),
				"existing_entries": operational.get("entries", []),
				"entry_status": "Ready" if job_write else _("Read only: no Job Card write permission"),
				"can_record_output": job_write, "can_correct_output": job_write,
			})
			if len(result) > MAX_BATCH_OUTPUT_ROWS:
				frappe.throw(_("More than {0} output rows match. Narrow the selected building or shift.").format(MAX_BATCH_OUTPUT_ROWS))
	return {"site": site, "shift_date": shift_date, "shift_type": shift_type, "building": building, "rows": result}


@frappe.whitelist(methods=["POST"])
def calculate_output_metrics(good_qty, rejected_qty=0, soph=None, period_minutes=0):
	"""Shared server-side calculation for both encoder modes."""
	return _output_calculation(good_qty, rejected_qty, soph or 0, period_minutes)


def _building_for_process_card(card, workstation):
	if not card.site:
		return None
	layouts = frappe.get_list(
		"Production Floor Layout", filters={"production_site": card.site},
		fields=["name", "layout_json"], limit_page_length=1,
	)
	if not layouts:
		return None
	try:
		data = json.loads(layouts[0].layout_json or "{}")
	except (TypeError, ValueError):
		return None
	for building in data.get("buildings", []):
		if any(row.get("kind") == "machine" and row.get("workstation") == workstation for row in building.get("interior", {}).get("elements", [])):
			return building.get("label")
	return None


@frappe.whitelist(methods=["GET"])
def get_process_card_context(process_card):
	"""Load a permission-checked Process Card and its native ERPNext Job Card facts."""
	card = _process_card(process_card)
	workstation = frappe.get_doc("Workstation", card.workstation)
	can_write = bool(frappe.has_permission("Process Card", "write", doc=card))
	can_record_card_output = can_write and card.status in {"Draft", "In Progress"}
	job_cards = []
	job_docs = []
	for row in card.jobs:
		job, work_order = _job_card(row.job_card, card.company, card.workstation, allow_historical=True)
		job_docs.append(job)
		job_payload = _job_card_payload(job)
		job_payload["work_order_status"] = work_order.status
		job_payload["can_record_output"] = (
			can_record_card_output
			and job.status != "Completed"
			and work_order.status not in {"Stopped", "Completed", "Cancelled"}
			and bool(frappe.has_permission("Job Card", "write", doc=job))
		)
		job_payload["can_correct_output"] = job_payload["can_record_output"]
		job_cards.append(job_payload)
	production_output = _production_output_summary(card, job_docs)
	can_record_output = can_record_card_output and any(job["can_record_output"] for job in job_cards)
	allowed_transitions = ALLOWED_TRANSITIONS.get(card.status, set()) - {card.status}
	if "Approved" in allowed_transitions and not (set(frappe.get_roles()) & {"Manufacturing Manager", "System Manager"}):
		allowed_transitions = allowed_transitions - {"Approved"}
	return {
		"process_card": {
			"name": card.name,
			"status": card.status,
			"company": card.company,
			"site": card.site,
			"workstation": workstation.name,
			"workstation_name": workstation.workstation_name or workstation.name,
			"workstation_type": workstation.workstation_type,
			"workstation_status": workstation.status,
			"workstation_description": workstation.description,
			"plant_floor": workstation.plant_floor,
			"building": _building_for_process_card(card, workstation.name),
			"shift_date": card.shift_date,
			"shift_type": card.shift_type,
			"shift_start": card.shift_start,
			"shift_end": card.shift_end,
		},
		"job_cards": job_cards,
		"production_output": production_output,
		"can_write": can_write,
		"can_record_output": can_record_output,
		"can_correct_output": can_record_output,
		"can_create": bool(frappe.has_permission("Process Card", "create")),
		"allowed_transitions": sorted(allowed_transitions),
	}


@frappe.whitelist(methods=["GET"])
def search_eligible_job_cards(process_card, search=None):
	card = _process_card(process_card)
	filters = {
		"company": card.company,
		"workstation": card.workstation,
		"docstatus": ["!=", 2],
		"status": ["not in", ["Completed", "Cancelled"]],
	}
	or_filters = None
	search = (search or "").strip()
	if search:
		pattern = f"%{search[:100]}%"
		or_filters = [
			["Job Card", "name", "like", pattern],
			["Job Card", "work_order", "like", pattern],
			["Job Card", "operation", "like", pattern],
			["Job Card", "production_item", "like", pattern],
		]
	rows = frappe.get_list(
		"Job Card", filters=filters, or_filters=or_filters,
		fields=["name", "work_order", "operation", "operation_id", "production_item", "for_quantity", "total_completed_qty", "status", "docstatus"],
		limit_page_length=MAX_JOB_CARDS_PER_SEARCH, order_by="modified desc",
	)
	linked = {row.job_card for row in card.jobs}
	result = []
	for row in rows:
		if row.name in linked or not row.work_order:
			continue
		work_orders = frappe.get_list(
			"Work Order",
			filters={
				"name": row.work_order,
				"company": card.company,
				"docstatus": 1,
				"status": ["not in", ["Stopped", "Completed", "Cancelled"]],
			},
			fields=["name"], limit_page_length=1,
		)
		if not work_orders:
			continue
		if row.operation_id and not frappe.db.exists(
			"Work Order Operation",
			{"name": row.operation_id, "parent": row.work_order, "operation": row.operation},
		):
			continue
		if not row.operation_id and frappe.db.exists("Work Order Operation", {"parent": row.work_order}):
			continue
		result.append(row)
	return result


def _editable_process_card(name):
	card = _process_card(name, "write")
	if card.status not in {"Draft", "In Progress"}:
		frappe.throw(_("Job Cards can only be changed while the Process Card is Draft or In Progress."))
	return card


def _lock_process_card(name):
	frappe.db.sql("select name from `tabProcess Card` where name=%s for update", name)
	return _editable_process_card(name)


@frappe.whitelist(methods=["POST"])
def add_job_cards(process_card, job_cards):
	try:
		names = frappe.parse_json(job_cards) if isinstance(job_cards, str) else job_cards
	except (TypeError, ValueError):
		frappe.throw(_("Select valid Job Cards."))
	if not isinstance(names, list) or not names or len(names) > MAX_JOB_CARDS_PER_REQUEST or any(not isinstance(name, str) or not name for name in names):
		frappe.throw(_("Select between one and {0} valid Job Cards.").format(MAX_JOB_CARDS_PER_REQUEST))
	if len(names) != len(set(names)):
		frappe.throw(_("A Job Card can only be selected once."))
	card = _lock_process_card(process_card)
	linked = {row.job_card for row in card.jobs}
	duplicates = linked.intersection(names)
	if duplicates:
		frappe.throw(_("Job Card {0} is already linked to this Process Card.").format(sorted(duplicates)[0]))
	for name in names:
		job, work_order = _job_card(name, card.company, card.workstation)
		card.append("jobs", {
			"job_card": job.name,
			"work_order": work_order.name,
			"operation": job.operation,
			"production_item": job.production_item,
		})
	card.save()
	return get_process_card_context(card.name)


@frappe.whitelist(methods=["POST"])
def remove_job_card(process_card, job_card):
	card = _lock_process_card(process_card)
	row = next((row for row in card.jobs if row.job_card == job_card), None)
	if not row:
		frappe.throw(_("Job Card is not linked to this Process Card."))
	card.remove(row)
	card.save()
	return get_process_card_context(card.name)


@frappe.whitelist(methods=["POST"])
def transition_status(process_card, status):
	frappe.db.sql("select name from `tabProcess Card` where name=%s for update", process_card)
	card = _process_card(process_card, "write")
	if status not in ALLOWED_TRANSITIONS.get(card.status, set()):
		frappe.throw(_("Invalid Process Card status transition from {0} to {1}.").format(card.status, status))
	if card.status == "For Approval" and status == "Approved":
		frappe.only_for("System Manager", "Manufacturing Manager")
	card.status = status
	card.save()
	return get_process_card_context(card.name)
