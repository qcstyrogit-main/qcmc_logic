import frappe
from frappe import _
from frappe.utils import flt


ROLL_TRIMMINGS_FIELD = "custom_roll_trimmings_"
RATIO_TOLERANCE = 0.000001


def apply_roll_formulation_required_qty(doc, method=None, validate_category_totals=True):
	"""Apply Roll BOM formulation percentages to Work Order required item quantities."""
	if doc.doctype != "Work Order" or not doc.get("bom_no") or not flt(doc.get("qty")):
		return

	bom = frappe.get_doc("BOM", doc.bom_no)
	if not is_roll_bom(bom):
		return

	formulation_categories = get_formulation_categories(bom)
	if not formulation_categories:
		return

	apply_roll_item_metadata(doc, formulation_categories)
	validate_roll_item_substitutions(doc, formulation_categories)
	if validate_category_totals:
		validate_formulation_category_totals(doc, formulation_categories)
	set_roll_item_details(doc)
	set_formulation_required_quantities(doc, bom)


@frappe.whitelist()
def preview_roll_formulation_required_items(doc):
	"""Return Work Order required items after applying Roll BOM formulation rules."""
	doc = get_work_order_doc(doc)
	bom = frappe.get_doc("BOM", doc.bom_no) if doc.get("bom_no") else None
	if not bom or not is_roll_bom(bom):
		return {
			"document_modified": doc.get("modified"),
			"required_items": None,
		}

	apply_roll_formulation_required_qty(doc, validate_category_totals=False)
	return {
		"document_modified": doc.get("modified"),
		"required_items": [row.as_dict() for row in doc.get("required_items", [])],
	}


@frappe.whitelist()
def get_roll_formulation_editor_data(doc):
	"""Return Roll formulation rows and BOM category targets for the editor dialog."""
	doc = get_work_order_doc(doc)
	bom = frappe.get_doc("BOM", doc.bom_no) if doc.get("bom_no") else None
	if not bom or not is_roll_bom(bom):
		frappe.throw(_("The selected BOM is not a Roll BOM."))

	formulation_categories = get_formulation_categories(bom)
	apply_roll_formulation_required_qty(doc, validate_category_totals=False)

	return get_roll_formulation_response(doc, formulation_categories)


@frappe.whitelist()
def validate_roll_formulation_editor(doc):
	"""Validate editor rows against BOM category targets and return calculated rows."""
	doc = get_work_order_doc(doc)
	bom = frappe.get_doc("BOM", doc.bom_no) if doc.get("bom_no") else None
	if not bom or not is_roll_bom(bom):
		frappe.throw(_("The selected BOM is not a Roll BOM."))

	formulation_categories = get_formulation_categories(bom)
	apply_roll_formulation_required_qty(doc, validate_category_totals=True)

	return get_roll_formulation_response(doc, formulation_categories)


def get_work_order_doc(doc):
	doc_data = (
		frappe.parse_json(doc)
		if isinstance(doc, str) and doc.lstrip().startswith(("{", "["))
		else doc
	)
	return (
		frappe.get_doc("Work Order", doc_data)
		if isinstance(doc_data, str)
		else frappe.get_doc(doc_data)
	)


def get_roll_formulation_response(doc, formulation_categories):
	categories = []
	for category in formulation_categories.values():
		categories.append(
			{
				"item_group": category["bom_item_group"],
				"material_tag": category["bom_material_tag"],
				"target_ratio_percent": category["target_ratio_percent"],
				"label": get_category_label(category),
			}
		)

	formulation_rows = []
	for row in doc.get("required_items", []):
		if not row.get("custom_bom_item_code"):
			continue

		category = formulation_categories.get(
			get_category_key(
				row.get("custom_bom_item_group"),
				row.get("custom_bom_material_tag"),
			)
		)
		formulation_rows.append(
			{
				"work_order_item_name": row.name,
				"item_code": row.item_code,
				"item_name": row.item_name,
				"item_group": row.get("custom_bom_item_group"),
				"material_tag": row.get("custom_bom_material_tag"),
				"material_ratio_percent": row.get("custom_material_ratio_percent"),
				"required_qty": row.required_qty,
				"category": get_category_label(category) if category else "",
			}
		)

	return {
		"document_modified": doc.get("modified"),
		"required_items": [row.as_dict() for row in doc.get("required_items", [])],
		"formulation_rows": formulation_rows,
		"categories": categories,
	}


def get_category_label(category):
	return _("{0} / {1}").format(
		category["bom_item_group"],
		category["bom_material_tag"] or _("Blank"),
	)


def is_roll_bom(bom):
	if bom.get("custom_is_roll_bom"):
		return True

	if not bom.get("item"):
		return False

	return is_roll_item_group(frappe.db.get_value("Item", bom.item, "item_group"))


def is_roll_item_group(item_group):
	return (item_group or "").strip().upper() == "ROLLS"


def get_formulation_categories(bom):
	categories = {}

	for bom_item in bom.get("items", []):
		if not is_roll_managed_bom_item(bom_item):
			continue

		item_code = bom_item.get("item_code")
		if not item_code:
			continue

		item_details = get_item_classification(item_code)
		if not item_details:
			continue

		category_key = get_category_key(
			item_details.item_group,
			item_details.custom_material_tag,
		)
		category = categories.setdefault(
			category_key,
			{
				"bom_item_group": item_details.item_group,
				"bom_material_tag": item_details.custom_material_tag,
				"include_in_formulation": 0,
				"apply_roll_trimming": 0,
				"target_ratio_percent": 0,
				"source_item_codes": [],
				"source_item_ratios": {},
			},
		)
		validate_category_calculation_method(category, bom_item)
		category["include_in_formulation"] = max(
			category["include_in_formulation"],
			flt(bom_item.get("custom_include_in_formulation")),
		)
		category["apply_roll_trimming"] = max(
			category["apply_roll_trimming"],
			flt(bom_item.get("custom_apply_roll_trimming")),
		)
		if item_code not in category["source_item_codes"]:
			category["source_item_codes"].append(item_code)
		if is_percentage_based_roll_item(bom_item):
			ratio = flt(bom_item.get("custom_material_ratio_percent"))
			category["target_ratio_percent"] += ratio
			category["source_item_ratios"][item_code] = (
				flt(category["source_item_ratios"].get(item_code)) + ratio
			)

	return categories


def validate_category_calculation_method(category, bom_item):
	if not category["source_item_codes"]:
		return

	include_in_formulation = flt(bom_item.get("custom_include_in_formulation"))
	apply_roll_trimming = flt(bom_item.get("custom_apply_roll_trimming"))
	if (
		include_in_formulation != flt(category["include_in_formulation"])
		or apply_roll_trimming != flt(category["apply_roll_trimming"])
	):
		frappe.throw(
			_(
				"Roll BOM materials with Item Group {0} and Material Tag {1} "
				"must use the same formulation and trimming settings."
			).format(
				frappe.bold(category["bom_item_group"]),
				frappe.bold(category["bom_material_tag"] or _("Blank")),
			)
		)


def is_roll_managed_bom_item(bom_item):
	return bom_item.get("custom_include_in_formulation")


def is_percentage_based_roll_item(bom_item):
	return bom_item.get("custom_include_in_formulation")


def apply_roll_item_metadata(doc, formulation_categories):
	category_totals = {}
	for row in doc.get("required_items", []):
		category_key = get_category_key(
			row.get("custom_bom_item_group"),
			row.get("custom_bom_material_tag"),
		)
		category_totals[category_key] = (
			flt(category_totals.get(category_key))
			+ flt(row.get("custom_material_ratio_percent"))
		)

	assigned_source_items = {
		row.get("custom_bom_item_code")
		for row in doc.get("required_items", [])
		if row.get("custom_bom_item_code")
		and flt(row.get("custom_material_ratio_percent"))
	}

	for row in doc.get("required_items", []):
		if row.get("custom_bom_item_code"):
			category = formulation_categories.get(
				get_category_key(
					row.get("custom_bom_item_group"),
					row.get("custom_bom_material_tag"),
				)
			)
			if not category:
				clear_roll_item_metadata(row)
				continue
		else:
			item_details = get_item_classification(row.get("item_code"))
			if not item_details:
				continue

			category = formulation_categories.get(
				get_category_key(
					item_details.item_group,
					item_details.custom_material_tag,
				)
			)
			if not category:
				continue

			row.custom_include_in_formulation = category["include_in_formulation"]
			row.custom_apply_roll_trimming = category["apply_roll_trimming"]
			row.custom_bom_item_code = (
				row.item_code
				if row.item_code in category["source_item_codes"]
				else category["source_item_codes"][0]
			)
			row.custom_bom_item_group = category["bom_item_group"]
			row.custom_bom_material_tag = category["bom_material_tag"]

		if (
			(
				row.get("custom_material_ratio_percent") in (None, "")
				or not flt(
					category_totals.get(
						get_category_key(
							category["bom_item_group"],
							category["bom_material_tag"],
						)
					)
				)
			)
			and row.item_code in category["source_item_ratios"]
			and row.item_code not in assigned_source_items
		):
			row.custom_material_ratio_percent = category["source_item_ratios"][row.item_code]

		assigned_source_items.add(row.custom_bom_item_code)


def clear_roll_item_metadata(row):
	row.custom_include_in_formulation = 0
	row.custom_apply_roll_trimming = 0
	row.custom_material_ratio_percent = 0
	row.custom_bom_item_code = None
	row.custom_bom_item_group = None
	row.custom_bom_material_tag = None


def validate_roll_item_substitutions(doc, formulation_categories):
	for row in doc.get("required_items", []):
		if not row.get("custom_bom_item_code"):
			continue

		if not row.get("item_code"):
			frappe.throw(_("Row #{0}: Roll material item is required.").format(row.idx))

		item_details = get_item_classification(row.item_code)
		if not item_details:
			frappe.throw(_("Row #{0}: Item {1} was not found.").format(row.idx, frappe.bold(row.item_code)))

		category_key = get_category_key(
			row.get("custom_bom_item_group"),
			row.get("custom_bom_material_tag"),
		)
		category = formulation_categories.get(category_key)
		if not category:
			frappe.throw(
				_("Row #{0}: Roll formulation category is no longer present in the BOM.").format(row.idx)
			)

		if item_details.item_group != category["bom_item_group"]:
			frappe.throw(
					_(
					"Row #{0}: Item {1} must belong to Item Group {2} for this Roll material row."
				).format(row.idx, frappe.bold(row.item_code), frappe.bold(category["bom_item_group"]))
			)

		if (item_details.custom_material_tag or "") != (category["bom_material_tag"] or ""):
			frappe.throw(
					_(
					"Row #{0}: Item {1} must use Material Tag {2} for this Roll material row."
				).format(
					row.idx,
					frappe.bold(row.item_code),
					frappe.bold(category["bom_material_tag"] or ""),
				)
			)


def validate_formulation_category_totals(doc, formulation_categories):
	actual_totals = {}
	for row in doc.get("required_items", []):
		if not row.get("custom_bom_item_code"):
			continue

		category_key = get_category_key(
			row.get("custom_bom_item_group"),
			row.get("custom_bom_material_tag"),
		)
		actual_totals[category_key] = (
			flt(actual_totals.get(category_key))
			+ flt(row.get("custom_material_ratio_percent"))
		)

	for category_key, category in formulation_categories.items():
		target = flt(category["target_ratio_percent"])
		actual = flt(actual_totals.get(category_key))
		if abs(actual - target) <= RATIO_TOLERANCE:
			continue

		frappe.throw(
			_(
				"Roll formulation category {0} / {1} must total {2}%. "
				"Current Work Order total is {3}%."
			).format(
				frappe.bold(category["bom_item_group"]),
				frappe.bold(category["bom_material_tag"] or _("Blank")),
				format_percent(target),
				format_percent(actual),
			)
		)


def set_roll_item_details(doc):
	from erpnext.stock.doctype.item.item import get_item_details

	for row in doc.get("required_items", []):
		if not row.get("custom_bom_item_code") or not row.get("item_code"):
			continue

		details = get_item_details(row.item_code, doc.get("company"))
		row.item_name = details.get("item_name")
		row.description = details.get("description")
		row.stock_uom = details.get("stock_uom")
		row.allow_alternative_item = details.get("allow_alternative_item")
		row.include_item_in_manufacturing = details.get("include_item_in_manufacturing")
		if not row.get("source_warehouse"):
			row.source_warehouse = details.get("default_warehouse") or doc.get("source_warehouse")


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
	if not item_code:
		return None

	return frappe.db.get_value(
		"Item",
		item_code,
		["item_group", "custom_material_tag"],
		as_dict=True,
	)


def get_category_key(item_group, material_tag):
	return item_group or "", material_tag or ""


def format_percent(value):
	return f"{round(flt(value), 6):g}"
