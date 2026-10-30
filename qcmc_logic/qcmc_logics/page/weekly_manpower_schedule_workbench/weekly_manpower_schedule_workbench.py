import frappe

from qcmc_logic.qcmc_logics.doctype.weekly_manpower_schedule.weekly_manpower_schedule import (
	get_schedule_workbench_data,
	save_schedule_workbench,
)


@frappe.whitelist()
def get_data(name):
	return get_schedule_workbench_data(name)


@frappe.whitelist()
def save(name, rows):
	return save_schedule_workbench(name, rows)
