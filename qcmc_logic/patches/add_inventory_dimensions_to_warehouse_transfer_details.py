import frappe

from qcmc_logic.overrides.inventory_dimension import (
	CustomInventoryDimension,
	WAREHOUSE_TRANSFER_DETAIL_DOCTYPE,
)


def execute():
	if not frappe.db.exists("DocType", WAREHOUSE_TRANSFER_DETAIL_DOCTYPE):
		return

	for dimension in frappe.get_all("Inventory Dimension", pluck="name"):
		doc = frappe.get_doc("Inventory Dimension", dimension)
		CustomInventoryDimension.add_warehouse_transfer_detail_fields(doc)

	frappe.clear_cache(doctype=WAREHOUSE_TRANSFER_DETAIL_DOCTYPE)
