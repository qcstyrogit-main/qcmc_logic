import frappe
from frappe import _


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
