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
		migrated_rows = []
		for row in list(doc.items):
			if not row.get("location"):
				continue
			existing = next((detail for detail in doc.custom_physical_count_results
				if detail.item_code == row.item_code
				and detail.warehouse == row.warehouse
				and detail.inventory_location == row.location), None)
			if existing:
				continue
			detail = doc.append("custom_physical_count_results", {
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
			# This is a data migration, not an edit to the reconciliation. Insert
			# the child row directly so unrelated legacy drafts that predate the
			# mandatory Default Warehouse rule do not fail full document validation.
			detail.db_insert()
			migrated_rows.append(row.name)

		if migrated_rows:
			frappe.db.delete("Stock Reconciliation Item", {"name": ["in", migrated_rows]})
			frappe.db.set_value(
				"Stock Reconciliation", name, "difference_amount", 0, update_modified=False
			)

	frappe.clear_cache(doctype="Stock Reconciliation")
