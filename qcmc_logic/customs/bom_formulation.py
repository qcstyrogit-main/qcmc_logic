import frappe
from frappe import _
from frappe.utils import flt


ROLL_ITEM_GROUP = "Rolls"
TOTAL_TOLERANCE = 0.000001


@frappe.whitelist()
def get_item_roll_details(item_code):
	"""Return roll-related Item details for BOM client scripts.

	The BOM form needs this even for users who can edit BOMs but do not have
	direct Item master read access.
	"""
	if not item_code:
		return {
			"item_group": None,
			"is_roll": False,
			"weight_per_unit": 0,
		}

	item = frappe.db.get_value(
		"Item",
		item_code,
		["item_group", "weight_per_unit"],
		as_dict=True,
	) or {}

	return {
		"item_group": item.get("item_group"),
		"is_roll": is_roll_item_group(item.get("item_group")),
		"weight_per_unit": flt(item.get("weight_per_unit")),
	}


def apply_roll_formulation_rules(doc, method=None):
	"""Derive roll flags/totals and validate formulation percentages for Roll BOMs."""
	if doc.doctype != "BOM":
		return

	is_roll = is_roll_bom(doc)
	doc.custom_is_roll_bom = 1 if is_roll else 0
	doc.custom_total_formulation_percent = get_formulation_total(doc)

	if not is_roll:
		return

	validate_roll_formulation(doc.custom_total_formulation_percent, get_formulation_items(doc))


def is_roll_bom(doc):
	if not doc.get("item"):
		return False

	return is_roll_item_group(frappe.db.get_value("Item", doc.item, "item_group"))


def is_roll_item_group(item_group):
	return (item_group or "").strip().upper() == ROLL_ITEM_GROUP.upper()


def get_formulation_items(doc):
	return [item for item in doc.get("items", []) if item.get("custom_include_in_formulation")]


def get_formulation_total(doc):
	return sum(flt(item.get("custom_material_ratio_percent")) for item in get_formulation_items(doc))


def validate_roll_formulation(total, formulation_items):
	if not formulation_items:
		frappe.throw(_("Roll BOM requires at least one formulation item."))

	if abs(flt(total) - 100) > TOTAL_TOLERANCE:
		frappe.throw(
			_("For Roll BOMs, formulation items must total 100%. Current total is {0}%.").format(
				format_percent(total)
			)
		)


def format_percent(value):
	return f"{round(flt(value), 6):g}"


# Work Order roll quantity logic:
# gross_input_qty = work_order_qty * (1 + custom_roll_trimmings / 100)
# BOM Items included in formulation contribute to the 100% total.
# BOM Items with custom_apply_roll_trimming use custom_material_ratio_percent
# against gross input quantity, even when excluded from the 100% formulation total.
