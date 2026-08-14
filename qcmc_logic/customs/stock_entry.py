import frappe
from frappe import _


def set_stock_entry_warehouse_code(doc, method=None):
	"""Set WH Code from the warehouse side implied by the selected Stock Entry Type."""
	warehouse_field = _get_stock_entry_wh_code_warehouse_field(doc)
	if not warehouse_field:
		return

	warehouses = _get_stock_entry_warehouses(doc, warehouse_field)
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


def _get_stock_entry_wh_code_warehouse_field(doc):
	source_warehouses = _get_stock_entry_warehouses(doc, "s_warehouse")
	target_warehouses = _get_stock_entry_warehouses(doc, "t_warehouse")

	if target_warehouses and not source_warehouses:
		return "t_warehouse"
	if source_warehouses and not target_warehouses:
		return "s_warehouse"

	if source_warehouses:
		return "s_warehouse"
	if target_warehouses:
		return "t_warehouse"

	return None


def _get_stock_entry_warehouses(doc, warehouse_field):
	header_field = "to_warehouse" if warehouse_field == "t_warehouse" else "from_warehouse"
	warehouses = {row.get(warehouse_field) for row in (doc.get("items") or []) if row.get(warehouse_field)}
	if doc.get(header_field):
		warehouses.add(doc.get(header_field))

	return warehouses


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
