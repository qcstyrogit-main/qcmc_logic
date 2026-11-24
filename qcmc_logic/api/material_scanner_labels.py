"""Permission-checked labels using Item defaults and the scanner's compact payload."""
import math

import frappe
from frappe import _

from qcmc_logic.api.generate_code import generate_qr


@frappe.whitelist()
def get_labels(items, pack_type="big"):
	pack_fields = {"big": ("custom_material_scanner_pack_qty", "Big Pack Qty"),
		"standard": ("custom_standard_pack_qty", "Standard Pack Qty")}
	if pack_type not in pack_fields:
		frappe.throw(_("Invalid pack type."))
	field, pack_label = pack_fields[pack_type]
	items = frappe.parse_json(items)
	if not isinstance(items, list) or not items or len(items) > 100:
		frappe.throw(_("Select between 1 and 100 Items."))
	labels = []
	for name in dict.fromkeys(items):
		if not isinstance(name, str):
			frappe.throw(_("Invalid Item selection."))
		item = frappe.get_doc("Item", name)
		item.check_permission("read")
		item.check_permission("print")
		quantity = float(item.get(field) or 0)
		if not item.is_stock_item or item.disabled:
			frappe.throw(_("Item {0} must be an enabled stock Item.").format(item.name))
		if not math.isfinite(quantity) or quantity <= 0:
			frappe.throw(_("Set a positive {0} on Item {1}.").format(pack_label, item.name))
		if not item.stock_uom:
			frappe.throw(_("Set the default UOM on Item {0}.").format(item.name))
		parts = [item.item_code, format(quantity, ".15g"), item.stock_uom, ""]
		if any(";" in part for part in parts):
			frappe.throw(_("Item code and UOM cannot contain a semicolon."))
		payload = ";".join(parts)
		labels.append({"item_code": item.item_code, "item_name": item.item_name,
			"quantity": parts[1], "uom": item.stock_uom, "pack_label": pack_label,
			"payload": payload, "qr": generate_qr(payload)})
	return labels
