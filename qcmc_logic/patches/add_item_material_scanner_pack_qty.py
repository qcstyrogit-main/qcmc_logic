"""Create reusable Item packing defaults from the read-only legacy snapshot."""
import json
from pathlib import Path

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


FIELD = "custom_material_scanner_pack_qty"


def execute():
	create_custom_fields({"Item": [{
		"fieldname": FIELD,
		"label": "Big Pack Qty",
		"fieldtype": "Float",
		"insert_after": "stock_uom",
		"description": "",
		"non_negative": 1,
	}]}, update=True)
	path = Path(__file__).resolve().parents[1] / "data" / "material_scanner_pack_quantities.json"
	quantities = json.loads(path.read_text())["quantities"]
	for item in frappe.get_all("Item", fields=["name", "item_code", FIELD]):
		quantity = quantities.get(item.item_code)
		if quantity is not None and not item.get(FIELD):
			frappe.db.set_value("Item", item.name, FIELD, quantity, update_modified=False)
