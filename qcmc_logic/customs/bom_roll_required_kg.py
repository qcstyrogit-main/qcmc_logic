import frappe
from frappe import _
from frappe.utils import flt


ROLL_KG_PRECISION = 3
ROLL_ITEM_GROUP = "ROLLS"


def apply_roll_required_kg(doc, method=None):
	"""Compute roll raw material quantities for BOM rows whose Item Group is Rolls."""
	if doc.doctype != "BOM":
		return

	fetch_finished_good_standard_weight(doc)

	roll_rows = get_roll_rows(doc)
	validate_single_roll_row(roll_rows)
	if not roll_rows:
		clear_roll_required_values(doc)
		return

	if not flt(doc.get("custom_roll_yield")):
		doc.custom_roll_yield = 1

	roll_row = roll_rows[0]
	roll_required_kg = calculate_roll_required_kg(doc, roll_row)
	roll_row.qty = roll_required_kg
	roll_row.custom_roll_required_kg = roll_required_kg


def fetch_finished_good_standard_weight(doc):
	if doc.get("custom_standard_weight_grams") or not doc.get("item"):
		return

	doc.custom_standard_weight_grams = flt(
		frappe.db.get_value("Item", doc.item, "weight_per_unit")
	)


def is_roll_item(item_code):
	if not item_code:
		return False

	item_group = frappe.db.get_value("Item", item_code, "item_group")
	return (item_group or "").strip().upper() == ROLL_ITEM_GROUP


def get_roll_rows(doc):
	return [row for row in doc.get("items", []) if is_roll_item(row.get("item_code"))]


def validate_single_roll_row(roll_rows):
	if len(roll_rows) <= 1:
		return

	frappe.throw(
		_(
			"Only one Roll item can be used as the BOM basis for Roll Required KG. "
			"Found Roll items: {0}."
		).format(
			", ".join(
				frappe.bold(row.get("item_code") or _("Row #{0}").format(row.idx))
				for row in roll_rows
			)
		)
	)


def clear_roll_required_values(doc):
	for row in doc.get("items", []):
		row.custom_roll_required_kg = 0


def calculate_roll_required_kg(doc, row):
	missing_values = get_missing_required_values(doc, row)
	if missing_values:
		frappe.throw(
			_("Row #{0}: Cannot compute Roll Required KG for item {1}. Missing: {2}.").format(
				row.idx,
				frappe.bold(row.get("item_code") or ""),
				", ".join(missing_values),
			)
		)

	bom_qty = flt(doc.get("quantity"))
	standard_weight_grams = flt(doc.get("custom_standard_weight_grams"))
	roll_yield = flt(doc.get("custom_roll_yield"))
	stabilizer_percent = flt(doc.get("custom_stabilizer_percent"))
	reject_percent = flt(doc.get("custom_reject_percent"))

	roll_required_kg = (
		((bom_qty * standard_weight_grams) / 1000)
		/ roll_yield
	) * (1 + ((stabilizer_percent + reject_percent) / 100))

	return round(flt(roll_required_kg), ROLL_KG_PRECISION)


def get_missing_required_values(doc, row):
	missing_values = []
	if not flt(doc.get("quantity")):
		missing_values.append(_("BOM Qty"))
	if not flt(doc.get("custom_standard_weight_grams")):
		missing_values.append(_("Standard Weight (g)"))
	if not flt(doc.get("custom_roll_yield")):
		missing_values.append(_("Roll Yield"))

	return missing_values
