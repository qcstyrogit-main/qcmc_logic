import frappe
from qcmc_logic.qcmc_logics.report.sales_order_delivery_scheduling import sales_order_delivery_scheduling


@frappe.whitelist()
def get_data(filters=None):
	filters = frappe._dict(frappe.parse_json(filters or "{}"))
	columns, rows, message, chart, summary = sales_order_delivery_scheduling.execute(filters)
	return {"columns": columns, "rows": rows, "message": message, "chart": chart, "summary": summary}


@frappe.whitelist()
def update_delivery_dates(so_details, delivery_date):
	return sales_order_delivery_scheduling.update_delivery_dates(so_details, delivery_date)


@frappe.whitelist()
def get_related_schedules(source_so_detail):
	return sales_order_delivery_scheduling.get_related_schedules(source_so_detail)


@frappe.whitelist()
def adjust_scheduled_quantity(source_so_detail, target_so_detail, new_qty, remarks=None):
	return sales_order_delivery_scheduling.adjust_scheduled_quantity(source_so_detail, target_so_detail, new_qty, remarks)


@frappe.whitelist()
def get_consolidation_candidates(so_details):
	return sales_order_delivery_scheduling.get_consolidation_candidates(so_details)


@frappe.whitelist()
def create_delivery_notes(so_details, consolidate_into=None):
	return sales_order_delivery_scheduling.create_delivery_notes(so_details, consolidate_into=consolidate_into)
