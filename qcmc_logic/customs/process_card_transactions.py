import math

import frappe
from frappe import _
from frappe.utils import get_datetime, time_diff_in_seconds


def _process_card(name, allow_cancelled=False):
	from qcmc_logic.api.process_card_workbench import _process_card as load_process_card

	card = load_process_card(name)
	if card.status == "Cancelled" and not allow_cancelled:
		frappe.throw(_("Cancelled Process Cards cannot be used for manufacturing transactions."))
	return card


def _linked_job_card(card, name):
	from qcmc_logic.api.process_card_workbench import _job_card

	if name not in {row.job_card for row in card.jobs}:
		frappe.throw(_("Job Card {0} is not linked to Process Card {1}.").format(name, card.name))
	return _job_card(name, card.company, card.workstation, allow_historical=True)[0]


def _validate_employee(name, company):
	employee = frappe.get_doc("Employee", name)
	employee.check_permission("read")
	if employee.status != "Active":
		frappe.throw(_("Employee {0} is not active.").format(name))
	if employee.company and employee.company != company:
		frappe.throw(_("Employee {0} belongs to a different Company.").format(name))
	return employee


def _participation_state(row):
	return tuple(
		row.get(field) or None
		for field in (
			"qcmc_process_card",
			"employee",
			"from_time",
			"to_time",
			"qcmc_pay_mode",
			"qcmc_mca_approval_reference",
		)
	)


def _validate_job_card_participation(doc):
	cards = {}
	previous = doc.get_doc_before_save()
	previous_rows = {
		row.name: row
		for row in ((previous.get("time_logs") or []) if previous else [])
		if row.name and row.get("qcmc_process_card") and row.get("employee")
		and int(row.get("qcmc_output_revision") or 0) <= 0
	}
	current_rows = {}
	for row in doc.get("time_logs") or []:
		card_name = row.get("qcmc_process_card")
		if not card_name:
			if row.get("qcmc_pay_mode") or row.get("qcmc_mca_approval_reference"):
				frappe.throw(_("Pay Mode and MCA Approval Reference require a Process Card."))
			continue

		if int(row.get("qcmc_output_revision") or 0) > 0:
			continue
		if row.name:
			current_rows[row.name] = row
		previous_row = previous_rows.get(row.name)
		unchanged_previous = (
			previous_row is not None
			and _participation_state(previous_row) == _participation_state(row)
		)

		if card_name not in cards:
			frappe.db.sql("select name from `tabProcess Card` where name=%s for update", card_name)
			cards[card_name] = _process_card(card_name, allow_cancelled=unchanged_previous)
		card = cards[card_name]
		if (
			card.status not in {"Draft", "In Progress"}
			and not unchanged_previous
		):
			frappe.throw(_("Participation cannot be added or changed after the Process Card is submitted for approval."))
		if card.status not in {"Draft", "In Progress"}:
			continue
		if not row.get("employee"):
			frappe.throw(_("A Process Card participation row must identify an Employee."))
		if row.get("qcmc_pay_mode") not in {"DR", "PCR"}:
			frappe.throw(_("Select DR or PCR for each Process Card participation row."))
		if doc.company != card.company or doc.workstation != card.workstation:
			frappe.throw(_("Participation Process Card must match the Job Card Company and Workstation."))
		_linked_job_card(card, doc.name)

		_validate_employee(row.employee, card.company)

		start = get_datetime(row.from_time) if row.from_time else None
		end = get_datetime(row.to_time) if row.to_time else None
		shift_start, shift_end = get_datetime(card.shift_start), get_datetime(card.shift_end)
		if not start or start < shift_start or start >= shift_end:
			frappe.throw(_("Employee participation must start within the Process Card shift."))
		if end and (end <= start or end > shift_end):
			frappe.throw(_("Employee participation must end after it starts and within the Process Card shift."))

	for row_name, previous_row in previous_rows.items():
		current_row = current_rows.get(row_name)
		if current_row and _participation_state(previous_row) == _participation_state(current_row):
			continue
		card_name = previous_row.qcmc_process_card
		if card_name not in cards:
			frappe.db.sql("select name from `tabProcess Card` where name=%s for update", card_name)
			cards[card_name] = _process_card(card_name, allow_cancelled=True)
		if cards[card_name].status not in {"Draft", "In Progress"}:
			frappe.throw(_("Participation cannot be removed or changed after the Process Card is submitted for approval."))

	_validate_participation_overlaps(doc, cards)


def _validate_participation_overlaps(doc, cards):
	for card in cards.values():
		rows = []
		for link in card.jobs:
			if link.job_card == doc.name:
				job = doc
			else:
				job = frappe.get_doc("Job Card", link.job_card)
				job.check_permission("read")
			for row in job.get("time_logs") or []:
				if (
					row.get("qcmc_process_card") == card.name
					and row.get("employee")
					and int(row.get("qcmc_output_revision") or 0) <= 0
				):
					rows.append((row, job.name))

		for index, (row, job_name) in enumerate(rows):
			start = get_datetime(row.from_time)
			end = get_datetime(row.to_time) if row.to_time else get_datetime(card.shift_end)
			for other, other_job_name in rows[index + 1 :]:
				if row.employee != other.employee:
					continue
				other_start = get_datetime(other.from_time)
				other_end = get_datetime(other.to_time) if other.to_time else get_datetime(card.shift_end)
				if start < other_end and other_start < end:
					frappe.throw(
						_("Employee {0} has overlapping participation on Job Cards {1} and {2}.").format(
							row.employee, job_name, other_job_name
						)
					)


def validate_job_card_participation(doc, method=None):
	_validate_job_card_participation(doc)


def validate_downtime_entry(doc, method=None):
	if not doc.get("qcmc_process_card"):
		if doc.get("qcmc_job_card"):
			frappe.throw(_("A Job Card downtime reference requires a Process Card."))
		return

	card = _process_card(doc.qcmc_process_card)
	if doc.workstation != card.workstation:
		frappe.throw(_("Downtime Workstation must match the Process Card Workstation."))
	if not doc.from_time or not doc.to_time:
		frappe.throw(_("Downtime From Time and To Time are required."))

	start, end = get_datetime(doc.from_time), get_datetime(doc.to_time)
	shift_start, shift_end = get_datetime(card.shift_start), get_datetime(card.shift_end)
	if start >= end or start < shift_start or end > shift_end:
		frappe.throw(_("Downtime interval must be positive and fall within the Process Card shift."))
	if doc.get("qcmc_job_card"):
		_linked_job_card(card, doc.qcmc_job_card)
	_validate_employee(doc.operator, card.company)

	frappe.db.sql("select name from `tabWorkstation` where name=%s for update", doc.workstation)
	overlaps = frappe.get_list(
		"Downtime Entry",
		filters={
			"qcmc_process_card": card.name,
			"name": ["!=", doc.name or ""],
			"from_time": ["<", end],
			"to_time": [">", start],
		},
		fields=["name"],
		limit_page_length=1,
	)
	if overlaps:
		frappe.throw(_("Downtime interval overlaps Downtime Entry {0}.").format(overlaps[0].name))
	doc.downtime = round(time_diff_in_seconds(end, start) / 60, 2)


def validate_asset_repair(doc, method=None):
	if not doc.get("qcmc_process_card"):
		if doc.get("qcmc_job_card"):
			frappe.throw(_("A Job Card breakdown reference requires a Process Card."))
		return

	card = _process_card(doc.qcmc_process_card)
	if not doc.get("qcmc_workstation") or doc.qcmc_workstation != card.workstation:
		frappe.throw(_("Breakdown Workstation must match the Process Card Workstation."))
	if doc.company and doc.company != card.company:
		frappe.throw(_("Asset Repair Company must match the Process Card Company."))
	if doc.get("qcmc_job_card"):
		_linked_job_card(card, doc.qcmc_job_card)
	if not doc.failure_date:
		frappe.throw(_("Breakdown Failure Date is required."))
	failure_date = get_datetime(doc.failure_date)
	if not get_datetime(card.shift_start) <= failure_date < get_datetime(card.shift_end):
		frappe.throw(_("Breakdown Failure Date must fall within the Process Card shift."))
	if not doc.get("custom_bd_class") or not doc.get("custom_nature_of_breakdown"):
		frappe.throw(_("Breakdown Class and Nature of Breakdown are required."))
	if doc.repair_status == "Completed" and not doc.get("custom_action_taken"):
		frappe.throw(_("Record the repair actions before completing the Asset Repair."))


def validate_quality_inspection(doc, method=None):
	if not doc.get("qcmc_process_card"):
		if doc.get("qcmc_output_time_log"):
			frappe.throw(_("A production output interval requires a Process Card."))
		return

	card = _process_card(doc.qcmc_process_card)
	if doc.reference_type != "Job Card" or not doc.reference_name:
		frappe.throw(_("A Process Card Quality Inspection must reference a Job Card."))
	job = _linked_job_card(card, doc.reference_name)
	if doc.item_code != job.production_item:
		frappe.throw(_("Quality Inspection Item must match the linked Job Card production item."))
	if doc.company and doc.company != card.company:
		frappe.throw(_("Quality Inspection Company must match the Process Card Company."))
	if doc.inspection_type != "In Process":
		frappe.throw(_("Process Card Quality Inspections must use Inspection Type In Process."))

	output = None
	if doc.get("qcmc_output_time_log"):
		output = next(
			(
				row for row in (job.get("time_logs") or [])
				if row.name == doc.qcmc_output_time_log
				and row.get("qcmc_process_card") == card.name
				and int(row.get("qcmc_output_revision") or 0) > 0
			),
			None,
		)
		if not output:
			frappe.throw(_("Production Output Interval must belong to this Job Card and Process Card."))
		duplicates = frappe.get_list(
			"Quality Inspection",
			filters={
				"qcmc_output_time_log": doc.qcmc_output_time_log,
				"docstatus": ["!=", 2],
				"name": ["!=", doc.name or ""],
			},
			fields=["name"],
			limit_page_length=1,
		)
		if duplicates:
			frappe.throw(_("Production Output Interval already has Quality Inspection {0}.").format(duplicates[0].name))

	qa_rejected_qty = 0.0
	for reading in doc.get("readings") or []:
		try:
			rejected_qty = float(reading.get("qcmc_rejected_qty") or 0)
		except (TypeError, ValueError):
			frappe.throw(_("Row {0}: QA Rejected Qty must be a finite nonnegative number.").format(reading.idx))
		if not math.isfinite(rejected_qty) or rejected_qty < 0:
			frappe.throw(_("Row {0}: QA Rejected Qty must be a finite nonnegative number.").format(reading.idx))
		if rejected_qty and (reading.status != "Rejected" or not reading.get("qcmc_reject_reason")):
			frappe.throw(_("Row {0}: QA rejection quantity requires a rejected result and a reject reason.").format(reading.idx))
		if reading.status == "Rejected" and not rejected_qty:
			frappe.throw(_("Row {0}: Record the quantity for this QA rejection.").format(reading.idx))
		qa_rejected_qty += rejected_qty
	if qa_rejected_qty:
		if not output:
			frappe.throw(_("QA rejection quantities must reference a production output interval."))
		output_qty = float(output.get("qcmc_good_qty") or 0) + float(output.get("qcmc_rejected_qty") or 0)
		if qa_rejected_qty > output_qty:
			frappe.throw(_("QA rejected quantity cannot exceed the linked production output quantity."))
