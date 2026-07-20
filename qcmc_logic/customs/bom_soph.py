from frappe.utils import flt


SOPH_PRECISION = 3
OPERATION_TIME_PRECISION = 3
PACKING_OPERATION_KEYWORDS = ("pack",)


def apply_bom_soph_and_operation_time(doc, method=None):
	"""Calculate machine SOPH and BOM operation time from existing BOM fields."""
	if doc.doctype != "BOM":
		return

	doc.custom_soph = calculate_soph(doc)
	apply_operation_times(doc)


def calculate_soph(doc):
	return round(
		flt(doc.get("custom_number_of_cavity"))
		* flt(doc.get("custom_rate_per_minute"))
		* 60,
		SOPH_PRECISION,
	)


def apply_operation_times(doc):
	for operation in doc.get("operations", []):
		soph = get_operation_soph(doc, operation)
		if not soph:
			operation.time_in_mins = 0
			continue

		operation.time_in_mins = round(
			(flt(doc.get("quantity")) * 60) / soph,
			OPERATION_TIME_PRECISION,
		)


def get_operation_soph(doc, operation):
	if is_packing_operation(operation):
		return flt(doc.get("custom_pack_soph"))

	return flt(doc.get("custom_soph"))


def is_packing_operation(operation):
	operation_name = (operation.get("operation") or "").strip().lower()
	return any(keyword in operation_name for keyword in PACKING_OPERATION_KEYWORDS)
