import frappe


def execute():
	from qcmc_logic.overrides.inventory_dimension import CustomInventoryDimension

	for name in frappe.get_all("Inventory Dimension", filters={"disabled": 0}, pluck="name"):
		dimension = frappe.get_doc("Inventory Dimension", name)
		CustomInventoryDimension.add_pick_list_item_fields(dimension)

	frappe.clear_cache(doctype="Pick List Item")
