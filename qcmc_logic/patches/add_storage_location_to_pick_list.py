import frappe


def execute():
	from qcmc_logic.overrides.inventory_dimension import CustomInventoryDimension

	filters = (
		{"disabled": 0}
		if frappe.get_meta("Inventory Dimension").has_field("disabled")
		else None
	)
	for name in frappe.get_all("Inventory Dimension", filters=filters, pluck="name"):
		dimension = frappe.get_doc("Inventory Dimension", name)
		CustomInventoryDimension.add_pick_list_item_fields(dimension)

	frappe.clear_cache(doctype="Pick List Item")
