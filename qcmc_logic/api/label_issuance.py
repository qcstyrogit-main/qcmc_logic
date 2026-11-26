import frappe
from frappe import _
from frappe.utils import flt, getdate


def _require_manufacturing_access():
	if not (set(frappe.get_roles()) & {"Manufacturing User", "Manufacturing Manager", "System Manager"}):
		frappe.throw(_("Manufacturing access required."), frappe.PermissionError)


@frappe.whitelist(methods=["GET"])
def get_rows(company, plant_floor, shift_date, shift_type=None):
	"""Return permission-filtered Process Card jobs for the issuance grid."""
	_require_manufacturing_access()
	if not company or not frappe.db.exists("Company", company):
		frappe.throw(_("Select a valid Company."))
	if not plant_floor or not frappe.db.exists("Plant Floor", plant_floor):
		frappe.throw(_("Select a valid Plant Floor."))
	if frappe.db.get_value("Plant Floor", plant_floor, "company") != company:
		frappe.throw(_("The selected Plant Floor does not belong to Company {0}.").format(company))
	if not shift_date:
		frappe.throw(_("Date is required."))

	workstations = frappe.get_list(
		"Workstation",
		filters={"plant_floor": plant_floor, "disabled": 0},
		pluck="name",
		limit_page_length=0,
	)
	if not workstations:
		return []

	filters = {"company": company, "workstation": ["in", workstations], "shift_date": getdate(shift_date)}
	if shift_type:
		filters["shift_type"] = shift_type
	cards = frappe.get_list(
		"Process Card",
		filters=filters,
		fields=["name", "workstation", "shift_date", "shift_type"],
		order_by="workstation asc, name asc",
		limit_page_length=500,
	)
	rows = []
	for card in cards:
		doc = frappe.get_doc("Process Card", card.name)
		for link in doc.jobs:
			if not link.job_card or not frappe.has_permission("Job Card", "read", link.job_card):
				continue
			job = frappe.get_doc("Job Card", link.job_card)
			bom = frappe.get_doc("BOM", job.bom_no) if job.bom_no and frappe.has_permission("BOM", "read", job.bom_no) else None
			standard_pack = flt(bom.get("custom_standard_pack")) if bom else 0
			big_pack = flt(bom.get("quantity")) if bom else 0
			qty = flt(job.for_quantity)
			work_order = frappe.db.get_value(
				"Work Order", job.work_order,
				["production_item", "item_name", "produced_qty", "sales_order"], as_dict=True,
			) if job.work_order else None
			customer_name = ""
			if work_order and work_order.sales_order:
				customer_name = frappe.db.get_value("Sales Order", work_order.sales_order, "customer_name") or ""
			rows.append({
				"machine": job.workstation or card.workstation,
				"process_card": card.name,
				"job_card": job.name,
				"job_qty": qty,
				"product_code": job.production_item or (work_order and work_order.production_item),
				"product_description": (work_order and work_order.item_name) or frappe.db.get_value("Item", job.production_item, "item_name") or "",
				"standard_pack_qty": standard_pack,
				"big_pack_qty": big_pack,
				"standard_labels": int(qty // standard_pack) if standard_pack else 0,
				"big_labels": int(qty // big_pack) if big_pack else 0,
				"material_lot_no": "",
				"roll_lot_no": "",
				"vac_lot_no": "",
				"sorted_by": "",
				"customer_name": customer_name,
				"uom": frappe.db.get_value("Item", job.production_item, "stock_uom") or "",
				"soph": flt(bom.get("custom_soph")) if bom else 0,
				"completed_qty": flt(job.total_completed_qty),
				"produced_qty": flt(work_order.produced_qty) if work_order else 0,
			})
	return rows
