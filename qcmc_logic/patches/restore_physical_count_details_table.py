import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.utils import flt, now_datetime


def execute():
	frappe.reload_doc("qcmc_logics", "doctype", "qcmc_physical_count_result")
	create_custom_fields({
		"Stock Reconciliation": [{
			"fieldname": "custom_physical_count_results_section",
			"label": "Physical Count Details",
			"fieldtype": "Section Break",
			"insert_after": "items",
			"depends_on": "eval:doc.custom_physical_count",
		}, {
			"fieldname": "custom_physical_count_results_summary",
			"label": "Physical Count Summary",
			"fieldtype": "HTML",
			"insert_after": "custom_physical_count_results_section",
		}, {
			"fieldname": "custom_physical_count_results",
			"label": "Physical Count Details",
			"fieldtype": "Table",
			"options": "QCMC Physical Count Result",
			"insert_after": "custom_physical_count_results_summary",
			"read_only": 1,
		}]
	}, update=True)

	for name in frappe.get_all(
		"Stock Reconciliation", filters={"custom_physical_count": 1, "docstatus": 0}, pluck="name"
	):
		doc = frappe.get_doc("Stock Reconciliation", name)
		if not doc.items:
			continue
		for row in list(doc.items):
			if not row.get("location"):
				continue
			existing = next((detail for detail in doc.custom_physical_count_results
				if detail.item_code == row.item_code
				and detail.warehouse == row.warehouse
				and detail.inventory_location == row.location), None)
			if existing:
				continue
			doc.append("custom_physical_count_results", {
				"submission_id": f"migrated:{name}:{row.name}",
				"item_code": row.item_code,
				"item_name": row.item_name,
				"warehouse": row.warehouse,
				"inventory_location": row.location,
				"inventory_location_id": row.location,
				"uom": row.stock_uom,
				"erp_quantity_before": row.current_qty,
				"physical_count": row.qty,
				"variance": (row.qty or 0) - (row.current_qty or 0),
				"adjustment_status": "Migrated",
				"submitted_at": now_datetime(),
				"status": "No adjustment required" if not flt(row.quantity_difference) else "Adjusted",
			})
		doc.set("items", [row for row in doc.items if not row.get("location")])
		doc.difference_amount = 0
		doc.save(ignore_permissions=True)

	frappe.clear_cache(doctype="Stock Reconciliation")
