from frappe.utils import flt


def normalize_bom_numeric_fields(doc, method=None):
	"""Coerce BOM percentage values before ERPNext performs arithmetic."""
	doc.cost_allocation_per = flt(doc.get("cost_allocation_per"))

	for item in doc.get("secondary_items", []):
		item.cost_allocation_per = flt(item.get("cost_allocation_per"))
