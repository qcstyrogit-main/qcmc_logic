import frappe
from frappe.utils import flt

from qcmc_logic.customs.bom_soph import is_packing_operation


OPERATION_TIME_PRECISION = 3


def apply_eps_secondary_packing_operations(doc, method=None):
	if doc.doctype != "Work Order" or not doc.bom_no or not doc.get("operations"):
		return
	if not frappe.get_meta("Work Order Operation").has_field("custom_bom_secondary_item"):
		return

	packing_operation = get_main_packing_operation(doc)
	if not packing_operation:
		return

	bom = frappe.get_cached_doc("BOM", doc.bom_no)
	secondary_items = get_secondary_packing_items(bom)
	remove_generated_secondary_packing_operations(doc)

	if not secondary_items:
		set_main_packing_operation_fields(doc, bom, packing_operation)
		doc.calculate_operating_cost()
		return

	set_main_packing_operation_fields(doc, bom, packing_operation)
	for secondary_item in secondary_items:
		add_secondary_packing_operation(doc, bom, packing_operation, secondary_item)

	reindex_operations(doc)
	doc.calculate_operating_cost()


def get_main_packing_operation(doc):
	for operation in doc.get("operations", []):
		if operation.get("custom_bom_secondary_item"):
			continue
		if is_packing_operation(operation):
			return operation

	return None


def get_secondary_packing_items(bom):
	return [
		row
		for row in bom.get("secondary_items", [])
		if flt(row.get("custom_pack_soph")) or row.get("custom_packing_workstation")
	]


def remove_generated_secondary_packing_operations(doc):
	doc.set(
		"operations",
		[
			row
			for row in doc.get("operations", [])
			if not row.get("custom_bom_secondary_item")
		],
	)


def set_main_packing_operation_fields(doc, bom, operation):
	pack_soph = flt(bom.get("custom_pack_soph"))
	operation.custom_eps_output_item = doc.production_item
	operation.custom_eps_output_type = "Main Item"
	operation.custom_pack_soph = pack_soph
	if pack_soph:
		operation.time_in_mins = calculate_time(doc.qty, pack_soph)


def add_secondary_packing_operation(doc, bom, source_operation, secondary_item):
	output_qty = get_work_order_secondary_qty(doc, bom, secondary_item)
	pack_soph = flt(secondary_item.get("custom_pack_soph"))
	target = doc.append("operations", {})

	for fieldname in get_copy_fields():
		target.set(fieldname, source_operation.get(fieldname))

	target.status = "Pending"
	target.completed_qty = 0
	target.actual_start_time = None
	target.actual_end_time = None
	target.actual_operation_time = 0
	target.actual_operating_cost = 0
	target.planned_start_time = None
	target.planned_end_time = None
	target.planned_operating_cost = 0
	target.custom_eps_output_item = secondary_item.item_code
	target.custom_eps_output_type = secondary_item.type
	target.custom_bom_secondary_item = secondary_item.name
	target.custom_pack_soph = pack_soph

	if secondary_item.get("custom_packing_workstation"):
		target.workstation = secondary_item.custom_packing_workstation
		target.hour_rate = 0

	if pack_soph:
		target.time_in_mins = calculate_time(output_qty, pack_soph)


def get_work_order_secondary_qty(doc, bom, secondary_item):
	bom_qty = flt(bom.quantity) or 1
	secondary_qty = flt(secondary_item.get("stock_qty")) or flt(secondary_item.get("qty"))
	return flt(doc.qty) * secondary_qty / bom_qty


def calculate_time(qty, soph):
	if not soph:
		return 0

	return round((flt(qty) * 60) / flt(soph), OPERATION_TIME_PRECISION)


def get_copy_fields():
	return [
		"operation",
		"description",
		"workstation",
		"workstation_type",
		"sequence_id",
		"bom",
		"bom_no",
		"finished_good",
		"is_subcontracted",
		"skip_material_transfer",
		"backflush_from_wip_warehouse",
		"source_warehouse",
		"wip_warehouse",
		"fg_warehouse",
		"quality_inspection_required",
		"batch_size",
		"fixed_time",
		"hour_rate",
		"time_in_mins",
	]


def reindex_operations(doc):
	for idx, operation in enumerate(doc.get("operations", []), start=1):
		operation.idx = idx
