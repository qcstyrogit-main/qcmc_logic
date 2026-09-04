import frappe
from frappe import _


def set_stock_entry_warehouse_code(doc, method=None):
	"""Set WH Code from the warehouse side implied by the selected Stock Entry Type."""
	warehouse_field = _get_stock_entry_wh_code_warehouse_field(doc)
	if not warehouse_field:
		return

	_validate_msjr_output_traceability(doc)

	target_warehouses = {
		row.t_warehouse for row in (doc.get("items") or []) if row.get("t_warehouse")
	}
	if doc.get("to_warehouse"):
		target_warehouses.add(doc.to_warehouse)

	if not target_warehouses:
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


def _validate_msjr_output_traceability(doc):
	required = {
		"custom_msrp_no": _("Machine Shop Project"),
		"custom_final_process": _("Final Process"),
		"custom_daily_job_report": _("Final Daily Job Report"),
	}
	missing = [label for field, label in required.items() if not doc.get(field)]
	if missing:
		frappe.throw(
			_("MSJR output receipt is missing traceability fields: {0}.").format(", ".join(missing)),
			title=_("Traceability Required"),
		)

	project = frappe.db.get_value(
		"Machine Shop Repairs and Project", doc.custom_msrp_no,
		["msjr_no", "workflow_state"], as_dict=True,
	)
	if not project or project.msjr_no != doc.msjr_no or project.workflow_state != "Completed":
		frappe.throw(_("Machine Shop Project must be the completed project linked to this MSJR."))

	process = frappe.db.get_value(
		"Machine Shop Repairs and Project Process", doc.custom_final_process,
		["parent", "process_name", "status"], as_dict=True,
	)
	if not process or process.parent != doc.custom_msrp_no or process.process_name != "FINAL INSPECTION" or process.status != "Completed":
		frappe.throw(_("Final Process must be the completed FINAL INSPECTION for this project."))

	report = frappe.db.get_value(
		"Daily Job Report", doc.custom_daily_job_report,
		["project_no", "process_no"], as_dict=True,
	)
	if not report or report.project_no != doc.custom_msrp_no or report.process_no != doc.custom_final_process:
		frappe.throw(_("Final Daily Job Report must belong to the selected FINAL INSPECTION process."))


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
		and doc.get("custom_job_card_time_log")
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
