import frappe
from frappe import _
from frappe.utils import flt


@frappe.whitelist()
def make_pick_list(job_card):
	"""Create an unsaved, location-aware Pick List for one Job Card."""
	job_card = str(job_card or "").strip()
	if not job_card or not frappe.db.exists("Job Card", job_card):
		frappe.throw(_("Job Card is required and must exist."))

	doc = frappe.get_doc("Job Card", job_card)
	doc.check_permission("read")
	frappe.has_permission("Pick List", "create", throw=True)

	if doc.docstatus == 2 or doc.status == "Cancelled":
		frappe.throw(_("Cancelled Job Card {0} cannot create a Pick List.").format(frappe.bold(doc.name)))
	if not doc.work_order or not frappe.db.exists("Work Order", doc.work_order):
		frappe.throw(_("Job Card {0} has no valid Job Order.").format(frappe.bold(doc.name)))
	if doc.skip_material_transfer:
		frappe.throw(_("Material Transfer is skipped for Job Card {0}.").format(frappe.bold(doc.name)))

	pending_for_qty = max(flt(doc.for_quantity) - flt(doc.transferred_qty), 0)
	if pending_for_qty <= 0:
		frappe.throw(_("All required materials have already been transferred for Job Card {0}.").format(frappe.bold(doc.name)))

	pick_list = frappe.new_doc("Pick List")
	pick_list.company = doc.company
	pick_list.purpose = "Material Transfer for Manufacture"
	pick_list.work_order = doc.work_order
	pick_list.for_qty = pending_for_qty
	pick_list.custom_job_card = doc.name

	for source in doc.get("items") or []:
		pending_qty = max(flt(source.required_qty) - flt(source.transferred_qty), 0)
		if pending_qty <= 0:
			continue
		stock_uom = source.stock_uom or frappe.get_cached_value("Item", source.item_code, "stock_uom")
		pick_list.append(
			"locations",
			{
				"item_code": source.item_code,
				"warehouse": source.source_warehouse or doc.source_warehouse,
				"qty": pending_qty,
				"stock_qty": pending_qty,
				"uom": stock_uom,
				"stock_uom": stock_uom,
				"conversion_factor": 1,
				"custom_job_card_item": source.name,
			},
		)

	if not pick_list.locations:
		frappe.throw(_("Job Card {0} has no pending raw materials.").format(frappe.bold(doc.name)))
	if any(not row.warehouse for row in pick_list.locations):
		frappe.throw(_("Every pending Job Card material must have a Source Warehouse."))

	pick_list.set_item_locations()
	return pick_list.as_dict()
