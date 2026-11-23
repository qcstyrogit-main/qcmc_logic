import frappe
from qcmc_logic.api import sales_order_scheduling_service as sales_order_scheduling


def get_data(filters=None):
	filters = frappe._dict(frappe.parse_json(filters or "{}"))
	columns, rows, message, chart, summary = sales_order_scheduling.execute(filters)
	return {"columns": columns, "rows": rows, "message": message, "chart": chart, "summary": summary}


def update_delivery_dates(so_details, delivery_date):
	return sales_order_scheduling.update_delivery_dates(so_details, delivery_date)


def get_related_schedules(source_so_detail):
	return sales_order_scheduling.get_related_schedules(source_so_detail)


def adjust_scheduled_quantity(source_so_detail, target_so_detail, new_qty, remarks=None):
	return sales_order_scheduling.adjust_scheduled_quantity(source_so_detail, target_so_detail, new_qty, remarks)


def get_consolidation_candidates(so_details):
	return sales_order_scheduling.get_consolidation_candidates(so_details)


def get_creation_preview(so_details):
	return sales_order_scheduling.get_creation_preview(so_details)


def create_delivery_notes(so_details, consolidate_into=None, requested_quantities=None):
	return sales_order_scheduling.create_delivery_notes(
		so_details, consolidate_into=consolidate_into, requested_quantities=requested_quantities
	)


def create_v2_delivery_notes(schedule_quantities, expected_schedule_state):
	from qcmc_logic.api.delivery_schedule_service import create_draft_delivery_notes
	return create_draft_delivery_notes(schedule_quantities, expected_schedule_state)


def create_v2_schedule(so_item, delivery_date, qty, remarks, expected_so_modified, expected_planned_qty):
	from qcmc_logic.api.delivery_schedule_service import create_schedule
	return create_schedule(so_item, delivery_date, qty, remarks, expected_so_modified, expected_planned_qty)
