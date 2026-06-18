import frappe
from frappe import _
from frappe.utils import flt


ROLL_TRIMMINGS_FIELD = "custom_roll_trimmings_"


def apply_roll_formulation_required_qty(doc, method=None):
	"""Apply Roll BOM formulation percentages to Work Order required item quantities."""
	if doc.doctype != "Work Order" or not doc.get("bom_no") or not flt(doc.get("qty")):
		return

	bom = frappe.get_doc("BOM", doc.bom_no)
	if not is_roll_bom(bom):
		return

	roll_items_by_item = get_roll_items_by_item(bom)
	if not roll_items_by_item:
		return

	apply_roll_item_metadata(doc, roll_items_by_item)
	validate_roll_item_substitutions(doc)
	set_formulation_required_quantities(doc, bom)


def is_roll_bom(bom):
	if bom.get("custom_is_roll_bom"):
		return True

	if not bom.get("item"):
		return False

	return frappe.db.get_value("Item", bom.item, "item_group") == "Rolls"


def get_roll_items_by_item(bom):
	roll_items_by_item = {}

	for bom_item in bom.get("items", []):
		if not is_roll_managed_bom_item(bom_item):
			continue

		item_code = bom_item.get("item_code")
		if not item_code:
			continue

		item_details = get_item_classification(item_code)
		if not item_details:
			continue

		existing = roll_items_by_item.setdefault(
			item_code,
			{
				"bom_item_code": item_code,
				"bom_item_group": item_details.item_group,
				"bom_material_tag": item_details.custom_material_tag,
				"include_in_formulation": 0,
				"apply_roll_trimming": 0,
				"material_ratio_percent": 0,
			},
		)
		existing["include_in_formulation"] = max(
			existing["include_in_formulation"], flt(bom_item.get("custom_include_in_formulation"))
		)
		existing["apply_roll_trimming"] = max(
			existing["apply_roll_trimming"], flt(bom_item.get("custom_apply_roll_trimming"))
		)
		if is_percentage_based_roll_item(bom_item):
			existing["material_ratio_percent"] += flt(bom_item.get("custom_material_ratio_percent"))

	return roll_items_by_item


def is_roll_managed_bom_item(bom_item):
	return bom_item.get("custom_include_in_formulation") or bom_item.get("custom_apply_roll_trimming")


def is_percentage_based_roll_item(bom_item):
	return bom_item.get("custom_include_in_formulation") or bom_item.get("custom_apply_roll_trimming")


def apply_roll_item_metadata(doc, roll_items_by_item):
	for row in doc.get("required_items", []):
		if row.get("custom_bom_item_code"):
			continue

		roll_item = roll_items_by_item.get(row.get("item_code"))
		if not roll_item:
			continue

		row.custom_include_in_formulation = roll_item["include_in_formulation"]
		row.custom_apply_roll_trimming = roll_item["apply_roll_trimming"]
		row.custom_material_ratio_percent = roll_item["material_ratio_percent"]
		row.custom_bom_item_code = roll_item["bom_item_code"]
		row.custom_bom_item_group = roll_item["bom_item_group"]
		row.custom_bom_material_tag = roll_item["bom_material_tag"]


def validate_roll_item_substitutions(doc):
	for row in doc.get("required_items", []):
		if not row.get("custom_bom_item_code"):
			continue

		if not row.get("item_code"):
			frappe.throw(_("Row #{0}: Roll material item is required.").format(row.idx))

		item_details = get_item_classification(row.item_code)
		if not item_details:
			frappe.throw(_("Row #{0}: Item {1} was not found.").format(row.idx, frappe.bold(row.item_code)))

		if item_details.item_group != row.get("custom_bom_item_group"):
			frappe.throw(
					_(
					"Row #{0}: Item {1} must belong to Item Group {2} for this Roll material row."
				).format(row.idx, frappe.bold(row.item_code), frappe.bold(row.custom_bom_item_group))
			)

		if (item_details.custom_material_tag or "") != (row.get("custom_bom_material_tag") or ""):
			frappe.throw(
					_(
					"Row #{0}: Item {1} must use Material Tag {2} for this Roll material row."
				).format(row.idx, frappe.bold(row.item_code), frappe.bold(row.custom_bom_material_tag or ""))
			)


def set_formulation_required_quantities(doc, bom):
	gross_input_qty = flt(doc.qty) * (1 + flt(bom.get(ROLL_TRIMMINGS_FIELD)) / 100)

	for row in doc.get("required_items", []):
		if not row.get("custom_bom_item_code"):
			continue

		if row.get("custom_apply_roll_trimming"):
			required_qty = gross_input_qty * flt(row.get("custom_material_ratio_percent")) / 100
		elif row.get("custom_include_in_formulation"):
			required_qty = flt(doc.qty) * flt(row.get("custom_material_ratio_percent")) / 100
		else:
			continue

		row.required_qty = round(flt(required_qty), row.precision("required_qty"))
		row.amount = flt(row.rate) * flt(row.required_qty)

def get_item_classification(item_code):
	return frappe.db.get_value(
		"Item",
		item_code,
		["item_group", "custom_material_tag"],
		as_dict=True,
	)
