import frappe
from erpnext.manufacturing.doctype.work_order.work_order import (
	get_default_warehouse as erpnext_get_default_warehouse,
)


@frappe.whitelist()
def get_default_warehouse(company=None):
	if not company:
		return {
			"wip_warehouse": None,
			"fg_warehouse": None,
			"scrap_warehouse": None,
		}

	return erpnext_get_default_warehouse(company)
