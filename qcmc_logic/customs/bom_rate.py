import frappe
from frappe.utils import flt


def fetch_missing_component_rates(doc, method=None):
	"""Restore BOM Item rates cleared by UI rate-hiding customizations."""
	if doc.doctype != "BOM":
		return

	if not doc.company:
		return

	ensure_bom_conversion_rates(doc)

	for item in doc.get("items", []):
		if not item.item_code or item.get("rate") not in (None, ""):
			continue

		item.rate = get_component_rate(doc, item)
		item.base_rate = flt(item.rate) * flt(doc.conversion_rate or 1)
		item.amount = flt(item.rate, item.precision("rate")) * flt(item.qty, item.precision("qty"))
		item.base_amount = flt(item.amount) * flt(doc.conversion_rate or 1)


def ensure_bom_conversion_rates(doc):
	if hasattr(doc, "set_conversion_rate"):
		doc.set_conversion_rate()

	if hasattr(doc, "set_plc_conversion_rate"):
		doc.set_plc_conversion_rate()


def get_component_rate(doc, item):
	if item.get("sourced_by_supplier"):
		return 0

	if frappe.db.get_value("Item", item.item_code, "is_customer_provided_item"):
		return 0

	if item.get("bom_no") and (
		item.get("is_phantom_item") or doc.get("set_rate_of_sub_assembly_item_based_on_bom")
	):
		return flt(doc.get_bom_unitcost(item.bom_no)) * flt(item.conversion_factor or 1)

	return doc.get_rm_rate(
		{
			"company": doc.company,
			"item_code": item.item_code,
			"bom_no": item.get("bom_no"),
			"qty": item.get("qty"),
			"uom": item.get("uom"),
			"stock_uom": item.get("stock_uom"),
			"conversion_factor": item.get("conversion_factor") or 1,
			"sourced_by_supplier": item.get("sourced_by_supplier"),
			"is_phantom_item": item.get("is_phantom_item"),
			"last_purchase_rate": item.get("last_purchase_rate"),
		},
		notify=False,
	)
